// SPDX-License-Identifier: MIT
#define _GNU_SOURCE
#ifdef NDEBUG
#error "This lab sender requires assertions enabled"
#endif
#include <arpa/inet.h>
#include <assert.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/random.h>
#include <sys/resource.h>
#include <sys/socket.h>
#include <sys/uio.h>
#include <time.h>
#include <unistd.h>

static double now(void) {
    struct timespec value;
    assert(!clock_gettime(CLOCK_MONOTONIC, &value));
    return value.tv_sec + value.tv_nsec / 1e9;
}

static int number(const char *text, int maximum) {
    char *end;
    long value = strtol(text, &end, 10);
    assert(*text && !*end && value > 0 && value <= maximum);
    return (int)value;
}

static int source_index(int flow, int sources) {
    assert(flow >= 0 && flow < 8192 && sources > 0 && sources <= 16);
    return flow % sources;
}

int main(int argc, char **argv) {
    if (argc == 2 && !strcmp(argv[1], "--self-test")) {
        for (int flows = 64; flows <= 8192; flows *= 128) for (int sources = 1; sources <= 16; sources *= 4) {
            int counts[16] = {0};
            for (int flow = 0; flow < flows; flow++) counts[source_index(flow, sources)]++;
            for (int source = 0; source < sources; source++) assert(counts[source] == flows / sources);
        }
        puts("PASS64/8192flows across one/four/sixteen sources; fixed lab-only address range");
        return 0;
    }
    assert(argc == 5 || argc == 6 || argc == 7 || argc == 9);
    char host[64];
    assert(!gethostname(host, sizeof(host)) && !strcmp(host, "kit-restore"));
    int pps = number(argv[1], 25000), seconds = number(argv[2], 900);
    int burst = number(argv[3], 4096), flows = number(argv[4], 8192);
    int sources = argc >= 7 ? number(argv[6], 16) : 1;
    int source_first=argc==9?number(argv[7],55):40;
    int port_first=argc==9?number(argv[8],65535):(flows==1?46000:40000);
    assert(source_first>=40 && source_first+sources<=56 && port_first>=40000 && port_first+flows<=65536);
    assert(flows >= sources && flows % sources == 0);
    unsigned char payload[256];
    if (argc >= 6) {
        assert(!strcmp(argv[5], "random") || !strcmp(argv[5], "bad-mac") ||
               !strcmp(argv[5], "valid-unknown") || !strcmp(argv[5], "captured-prefix"));
        char path[128];
        assert(snprintf(path, sizeof(path), "/root/prefilter/%s.packet", argv[5]) > 0);
        FILE *file = fopen(path, "rb");
        assert(file && fread(payload, 1, sizeof(payload), file) == sizeof(payload));
        assert(fgetc(file) == EOF && !ferror(file));
        fclose(file);
    } else assert(getrandom(payload, sizeof(payload), 0) == (ssize_t)sizeof(payload));
    struct sockaddr_in target = { .sin_family = AF_INET, .sin_port = htons(32497) };
    assert(inet_pton(AF_INET, "192.168.76.10", &target.sin_addr) == 1);
    struct rlimit descriptors;
    assert(!getrlimit(RLIMIT_NOFILE,&descriptors));
    if (descriptors.rlim_cur<(rlim_t)flows+64) {
        descriptors.rlim_cur=(rlim_t)flows+64;assert(descriptors.rlim_cur<=descriptors.rlim_max);
        assert(!setrlimit(RLIMIT_NOFILE,&descriptors));
    }
    int *sockets=malloc((size_t)flows*sizeof(*sockets));assert(sockets);
    for (int i = 0; i < flows; i++) {
        sockets[i] = socket(AF_INET, SOCK_DGRAM, 0);
        assert(sockets[i] >= 0);
        struct sockaddr_in source = { .sin_family = AF_INET, .sin_port = htons(port_first + i) };
        char address[32];
        assert(snprintf(address, sizeof(address), "192.168.76.%d", source_first + source_index(i, sources)) > 0);
        assert(inet_pton(AF_INET, address, &source.sin_addr) == 1);
        assert(!bind(sockets[i], (struct sockaddr *)&source, sizeof(source)));
    }
    struct iovec iov = { .iov_base = payload, .iov_len = sizeof(payload) };
    struct mmsghdr messages[64] = {0};
    for (int i = 0; i < 64; i++) {
        messages[i].msg_hdr.msg_name = &target;
        messages[i].msg_hdr.msg_namelen = sizeof(target);
        messages[i].msg_hdr.msg_iov = &iov;
        messages[i].msg_hdr.msg_iovlen = 1;
    }
    int sent = 0, total = pps * seconds, bursts = 0;
    int source_packets[16] = {0};
    struct burst_record { double begin, end; int packets; } records[16384];
    assert((total + burst - 1) / burst <= 16384);
    double start = now(), min_span = 1e9, max_span = 0;
    while (sent < total) {
        int remaining = total - sent < burst ? total - sent : burst;
        int burst_packets = remaining;
        double began = now();
        while (remaining) {
            int count = remaining < 64 ? remaining : 64;
            int flow = (sent / 64) % flows;
            int result = sendmmsg(sockets[flow], messages, count, 0);
            if (result < 0 && errno == EINTR) continue;
            assert(result > 0 && result <= count);
            source_packets[source_index(flow, sources)] += result;
            sent += result;
            remaining -= result;
        }
        double span = now() - began;
        if (span < min_span) min_span = span;
        if (span > max_span) max_span = span;
        records[bursts++] = (struct burst_record){ began - start, now() - start, burst_packets };
        double deadline = start + (double)sent / pps;
        struct timespec wake = { .tv_sec = (time_t)deadline, .tv_nsec = (long)((deadline - (time_t)deadline) * 1e9) };
        int result;
        do { result = clock_nanosleep(CLOCK_MONOTONIC, TIMER_ABSTIME, &wake, NULL); } while (result == EINTR);
        assert(!result);
    }
    double elapsed = now() - start;
    struct rusage resource;
    assert(!getrusage(RUSAGE_SELF, &resource));
    printf("{\"sent\":%d,\"seconds\":%.6f,\"pps\":%.3f,\"flows\":%d,\"burst_packets\":%d,\"bursts\":%d,\"min_burst_send_seconds\":%.6f,\"max_burst_send_seconds\":%.6f,\"user_cpu_seconds\":%.6f,\"system_cpu_seconds\":%.6f,\"voluntary_switches\":%ld,\"involuntary_switches\":%ld,\"burst_records\":[",
           sent, elapsed, sent / elapsed, flows, burst, bursts, min_span, max_span,
           resource.ru_utime.tv_sec + resource.ru_utime.tv_usec / 1e6,
           resource.ru_stime.tv_sec + resource.ru_stime.tv_usec / 1e6,
           resource.ru_nvcsw, resource.ru_nivcsw);
    for (int i = 0; i < bursts; i++)
        printf("%s[%.9f,%.9f,%d]", i ? "," : "", records[i].begin, records[i].end, records[i].packets);
    printf("],\"source_count\":%d,\"source_first\":%d,\"port_first\":%d,\"source_packets\":{", sources,source_first,port_first);
    for (int source = 0; source < sources; source++)
        printf("%s\"192.168.76.%d\":%d", source ? "," : "", source_first + source, source_packets[source]);
    puts("}}");
    for (int i = 0; i < flows; i++) close(sockets[i]);
    free(sockets);
    return 0;
}
