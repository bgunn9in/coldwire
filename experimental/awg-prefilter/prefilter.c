/* SPDX-License-Identifier: MIT
 * LAB PROTOTYPE: AWG 3.1 prefilter, not client authentication.
 */
#define _GNU_SOURCE
#include <arpa/inet.h>
#include <errno.h>
#include <fcntl.h>
#include <linux/netfilter.h>
#include <linux/netfilter/nfnetlink.h>
#include <linux/netlink.h>
#include <libnetfilter_queue/libnetfilter_queue.h>
#include <openssl/core_names.h>
#include <openssl/crypto.h>
#include <openssl/evp.h>
#include <openssl/params.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/uio.h>
#include <time.h>
#include <unistd.h>

enum verdict { MALFORMED, HEADER, MAC, CRYPTO, INIT, RESPONSE, COOKIE, DATA, REASONS };
static const char *names[] = {"malformed", "header", "mac1", "crypto", "init", "response", "cookie", "transport"};
/* Largest IPv4 header, UDP header, AWG nonce and initiation through MAC1. */
static unsigned copy_range = 60 + 8 + 12 + 148 - 16;
static uint32_t paddings[4] = {12, 12, 12, 12};
static uint32_t headers[4][2] = {{1,1}, {2,2}, {3,3}, {4,4}};
static int random_trailers = 1; /* Legacy two-key files accepted trailers. */
/* The lab offers bursts up to 4096 packets; 2048 overflowed on the faster backend. */
enum { QUEUE_MAXLEN = 4096 };
static uint64_t counts[REASONS], bytes, copied_bytes, netlink_enobufs;
static uint64_t receive_calls, received_datagrams, send_calls, submitted_verdicts, verdict_missing;
static unsigned char hpk[32], mac_key[32];
static EVP_CIPHER_CTX *cipher;
static EVP_MAC *algorithm;
static EVP_MAC_CTX *mac;
static volatile sig_atomic_t stopping, reporting;

#ifdef PREFILTER_BATCH
enum { BATCH_SIZE = 16, DATAGRAM_SIZE = 8192 };
static int queue_fd;
static uint16_t queue_number;
static unsigned int verdict_count;
static char verdict_buffers[BATCH_SIZE][64] __attribute__((aligned));
static struct iovec verdict_iov[BATCH_SIZE];
#endif

#ifdef PREFILTER_PROFILE
static uint64_t receive_ns, inspect_ns, header_ns, handshake_ns, verdict_ns;
static uint64_t thread_cpu_ns(void) {
    struct timespec now;
    if (clock_gettime(CLOCK_THREAD_CPUTIME_ID, &now)) abort();
    return (uint64_t)now.tv_sec * 1000000000u + (uint64_t)now.tv_nsec;
}
#define TIMER_START(name) uint64_t name = thread_cpu_ns()
#define TIMER_STOP(name, total) ((total) += thread_cpu_ns() - (name))
#else
#define TIMER_START(name) ((void)0)
#define TIMER_STOP(name, total) ((void)0)
#endif

static void fail(const char *message) {
    fprintf(stderr, "%s\n", message);
    exit(1);
}

static void signal_handler(int number) {
    if (number == SIGUSR1) reporting = 1;
    else stopping = 1;
}

static void report(void) {
    printf("{\"bytes\":%llu,\"copied_bytes\":%llu,\"netlink_enobufs\":%llu",
           (unsigned long long)bytes, (unsigned long long)copied_bytes,
           (unsigned long long)netlink_enobufs);
    printf(",\"verdict_missing\":%llu", (unsigned long long)verdict_missing);
    for (int i = 0; i < REASONS; i++)
        printf(",\"%s\":%llu", names[i], (unsigned long long)counts[i]);
    printf(",\"receive_calls\":%llu,\"received_datagrams\":%llu,\"send_calls\":%llu,\"submitted_verdicts\":%llu",
           (unsigned long long)receive_calls, (unsigned long long)received_datagrams,
           (unsigned long long)send_calls, (unsigned long long)submitted_verdicts);
#ifdef PREFILTER_PROFILE
    printf(",\"receive_cpu_ns\":%llu,\"inspect_cpu_ns\":%llu,\"header_cpu_ns\":%llu,\"handshake_cpu_ns\":%llu,\"verdict_cpu_ns\":%llu",
           (unsigned long long)receive_ns, (unsigned long long)inspect_ns,
           (unsigned long long)header_ns, (unsigned long long)handshake_ns,
           (unsigned long long)verdict_ns);
#endif
    puts("}");
    fflush(stdout);
}

static void decode_key(const char *line, const char *prefix, unsigned char *key) {
    unsigned char decoded[33], canonical[45];
    size_t length = strlen(prefix);
    if (strncmp(line, prefix, length) || strlen(line + length) != 44 ||
        EVP_DecodeBlock(decoded, (const unsigned char *)line + length, 44) != 33 ||
        line[length + 43] != '=') fail("Invalid key file");
    EVP_EncodeBlock(canonical, decoded, 32);
    if (memcmp(canonical, line + length, 44)) fail("Noncanonical base64 key");
    memcpy(key, decoded, 32);
    OPENSSL_cleanse(decoded, sizeof(decoded));
}

static uint32_t wire_number(const char *text) {
    if (!*text) fail("Missing wire parameter");
    for (const char *p=text; *p; p++) if (*p<'0' || *p>'9') fail("Invalid wire parameter");
    char *end; errno=0;
    unsigned long value=strtoul(text,&end,10);
    if (errno || *end || value>UINT32_MAX) fail("Wire parameter out of range");
    return (uint32_t)value;
}

static void wire_parameter(char *line, unsigned *seen) {
    char *value=strchr(line,'=');
    if (!value) fail("Invalid wire parameter");
    *value++=0;
    unsigned index, bit;
    if (strlen(line)==2 && line[1]>='1' && line[1]<='4' && (line[0]=='S' || line[0]=='H')) {
        index=(unsigned)(line[1]-'1');bit=1u<<(index+(line[0]=='S'?0:4));
        if (*seen&bit) fail("Duplicate wire parameter");
        if (line[0]=='S') paddings[index]=wire_number(value);
        else {
            char *dash=strchr(value,'-');
            if (dash) *dash++=0;
            headers[index][0]=wire_number(value);
            headers[index][1]=dash?wire_number(dash):headers[index][0];
        }
    } else if (!strcmp(line,"RandomTrailers")) {
        bit=1u<<8;
        if (*seen&bit || (strcmp(value,"0") && strcmp(value,"1"))) fail("Invalid trailer parameter");
        random_trailers=value[0]=='1';
    } else fail("Unknown wire parameter");
    *seen|=bit;
}

static void load_keys(const char *path) {
    int fd = open(path, O_RDONLY | O_NOFOLLOW);
    struct stat st;
    if (fd < 0 || fstat(fd, &st) || !S_ISREG(st.st_mode) ||
        st.st_uid != geteuid() || (st.st_mode & 077)) fail("Key file must be owned by the current user, regular, and mode 0600 or stricter");
    FILE *file = fdopen(fd, "r");
    char line[128];
    unsigned char public_key[32], material[40];
    if (!file || !fgets(line, sizeof(line), file)) fail("Cannot read key file");
    line[strcspn(line, "\n")] = 0;
    decode_key(line, "HeaderProtectionKey=", hpk);
    if (!fgets(line, sizeof(line), file)) fail("Missing server public key");
    line[strcspn(line, "\n")] = 0;
    decode_key(line, "ServerPublicKey=", public_key);
    unsigned seen=0;
    while (fgets(line,sizeof(line),file)) {
        if (!strchr(line,'\n') && !feof(file)) fail("Wire parameter too long");
        line[strcspn(line,"\n")]=0;wire_parameter(line,&seen);
    }
    if (ferror(file) || (seen && seen!=511)) fail("Incomplete wire parameters");
    fclose(file);
    const unsigned sizes[4]={148,92,64,32},needed[4]={132,76,4,4};
    copy_range=0;
    for (unsigned i=0;i<4;i++) {
        if (paddings[i]<12 || paddings[i]>65507-sizes[i] || headers[i][0]>headers[i][1]) fail("Invalid wire parameters");
        for (unsigned j=0;j<i;j++)
            if (headers[i][0]<=headers[j][1] && headers[j][0]<=headers[i][1]) fail("Overlapping header ranges");
        unsigned required=60+8+paddings[i]+needed[i];
        if (required>copy_range) copy_range=required;
    }
    /* NFQA_PAYLOAD is a 16-bit attribute; message fields end before MAC2/tag. */
    if (copy_range>65531) copy_range=65531;
    OPENSSL_cleanse(line, sizeof(line));
    memcpy(material, "mac1----", 8);
    memcpy(material + 8, public_key, 32);
    unsigned int length = 0;
    if (!EVP_Digest(material, sizeof(material), mac_key, &length, EVP_blake2s256(), NULL) || length != 32)
        fail("BLAKE2s initialization failed");
    cipher = EVP_CIPHER_CTX_new();
    algorithm = EVP_MAC_fetch(NULL, "BLAKE2SMAC", NULL);
    if (!cipher || !algorithm || !(mac = EVP_MAC_CTX_new(algorithm))) fail("OpenSSL initialization failed");
}

static uint16_t be16(const unsigned char *p) { return (uint16_t)((p[0] << 8) | p[1]); }

static enum verdict inspect(const unsigned char *ip, size_t length, size_t original_length) {
    size_t required_copy = original_length < copy_range ? original_length : copy_range;
    if (length > original_length || length < required_copy) return MALFORMED;
    if (length < 28 || ip[0] >> 4 != 4 || ip[9] != 17) return MALFORMED;
    size_t ihl = (ip[0] & 15) * 4u, total = be16(ip + 2);
    if (ihl < 20 || ihl + 8 > length || total != original_length || (be16(ip + 6) & 0x3fff)) return MALFORMED;
    const unsigned char *udp = ip + ihl;
    size_t udp_length = be16(udp + 4);
    if (udp_length < 8 || ihl + udp_length != total) return MALFORMED;
    const unsigned char *payload = udp + 8;
    size_t size = udp_length - 8;
    if (size < 16) return HEADER;
    if (length < ihl + 8 + 16) return MALFORMED;
    unsigned char iv[16] = {0}, plain[148 - 16], mask[4]={0};
    memcpy(iv + 4, payload, 12);
    int produced = 0;
    TIMER_START(header_start);
    if (!EVP_EncryptInit_ex(cipher, EVP_chacha20(), NULL, hpk, iv) ||
        !EVP_EncryptUpdate(cipher, mask, &produced, mask, 4) || produced != 4) return CRYPTO;
    unsigned selected=4;
    const unsigned sizes[4]={148,92,64,32};
    for (unsigned i=0;i<4;i++) {
        if (size<paddings[i]+sizes[i] || (i<3 && !random_trailers && size!=paddings[i]+sizes[i])) continue;
        if (length<ihl+8+paddings[i]+4) return MALFORMED;
        const unsigned char *field=payload+paddings[i];
        uint32_t type=(uint32_t)(field[0]^mask[0]) | ((uint32_t)(field[1]^mask[1])<<8) |
                      ((uint32_t)(field[2]^mask[2])<<16) | ((uint32_t)(field[3]^mask[3])<<24);
        if (type>=headers[i][0] && type<=headers[i][1]) {selected=i;break;}
    }
    TIMER_STOP(header_start, header_ns);
    if (selected==4) return HEADER;
    if (selected>=2) return selected==2?COOKIE:DATA;
    size_t fixed=sizes[selected],padding=paddings[selected];
    for (unsigned i=0;i<4;i++) plain[i]=payload[padding+i]^mask[i];
    if (length < ihl + 8 + padding + fixed - 16) return MALFORMED;
    TIMER_START(handshake_start);
    if (!EVP_EncryptUpdate(cipher, plain + 4, &produced, payload + padding + 4, (int)fixed - 20) ||
        produced != (int)fixed - 20) return CRYPTO;
    unsigned char expected[16];
    size_t output_size = 0, wanted = sizeof(expected);
    OSSL_PARAM params[] = { OSSL_PARAM_construct_size_t(OSSL_MAC_PARAM_SIZE, &wanted), OSSL_PARAM_construct_end() };
    if (!EVP_MAC_init(mac, mac_key, 32, params) || !EVP_MAC_update(mac, plain, fixed - 32) ||
        !EVP_MAC_final(mac, expected, &output_size, sizeof(expected)) || output_size != 16) return CRYPTO;
    TIMER_STOP(handshake_start, handshake_ns);
    if (CRYPTO_memcmp(expected, plain + fixed - 32, 16)) return MAC;
    return selected==0?INIT:RESPONSE;
}

#ifdef PREFILTER_BATCH
static int flush_verdicts(void) {
    if (!verdict_count) return 0;
    struct sockaddr_nl kernel = { .nl_family = AF_NETLINK };
    struct msghdr message = {
        .msg_name = &kernel, .msg_namelen = sizeof(kernel),
        .msg_iov = verdict_iov, .msg_iovlen = verdict_count
    };
    size_t wanted = 0;
    for (unsigned int i = 0; i < verdict_count; i++) wanted += verdict_iov[i].iov_len;
    TIMER_START(verdict_start);
    ssize_t sent;
    do {
        send_calls++;
        sent = sendmsg(queue_fd, &message, 0);
    } while (sent < 0 && errno == EINTR && !stopping);
    int send_errno = sent >= 0 && (size_t)sent != wanted ? EIO : errno;
    TIMER_STOP(verdict_start, verdict_ns);
    if (sent < 0 || (size_t)sent != wanted) { errno = send_errno; return -1; }
    submitted_verdicts += verdict_count;
    verdict_count = 0;
    return 0;
}
#endif

static uint32_t verdict_mark(enum verdict reason, uint32_t existing) {
#ifdef PREFILTER_HANDSHAKE_MARK
    const uint32_t handshake = UINT32_C(0x20000000);
    const uint32_t classified = UINT32_C(0x40000000);
    return (existing & ~(handshake | classified)) | classified |
           ((reason == INIT || reason == RESPONSE || reason == COOKIE) ? handshake : 0);
#else
    (void)reason;
    return existing;
#endif
}

static int submit_verdict(struct nfq_q_handle *queue, uint32_t id, uint32_t verdict, uint32_t mark) {
#ifndef PREFILTER_HANDSHAKE_MARK
    (void)mark;
#endif
#ifdef PREFILTER_BATCH
    (void)queue;
    /* Each message addresses one inspected packet, including across ID gaps/wrap. */
    struct nlmsghdr *header = nfq_nlmsg_put(verdict_buffers[verdict_count], NFQNL_MSG_VERDICT, queue_number);
    header->nlmsg_flags = NLM_F_REQUEST;
    nfq_nlmsg_verdict_put(header, (int)id, (int)verdict);
#ifdef PREFILTER_HANDSHAKE_MARK
    nfq_nlmsg_verdict_put_mark(header, mark);
#endif
    verdict_iov[verdict_count] = (struct iovec){ .iov_base = header, .iov_len = header->nlmsg_len };
    verdict_count++;
    return verdict_count == BATCH_SIZE ? flush_verdicts() : 0;
#else
    TIMER_START(verdict_start);
    send_calls++;
#ifdef PREFILTER_HANDSHAKE_MARK
    int result = nfq_set_verdict2(queue, id, verdict, mark, 0, NULL);
#else
    int result = nfq_set_verdict(queue, id, verdict, 0, NULL);
#endif
    int send_errno = errno;
    TIMER_STOP(verdict_start, verdict_ns);
    if (result >= 0) submitted_verdicts++;
    errno = send_errno;
    return result;
#endif
}

static int callback(struct nfq_q_handle *queue, struct nfgenmsg *message, struct nfq_data *data, void *context) {
    (void)message;
    struct nfqnl_msg_packet_hdr *header = nfq_get_msg_packet_hdr(data);
    if (!header) return -1;
    unsigned char *packet = NULL;
    int length = nfq_get_payload(data, &packet);
    size_t original_length = *(size_t *)context;
    if (!original_length && length > 0) original_length = (size_t)length;
    TIMER_START(inspect_start);
    enum verdict reason = length > 0 ? inspect(packet, (size_t)length, original_length) : MALFORMED;
    TIMER_STOP(inspect_start, inspect_ns);
    counts[reason]++;
    if (length > 0) { bytes += original_length; copied_bytes += (unsigned int)length; }
    return submit_verdict(queue, ntohl(header->packet_id), reason >= INIT ? NF_ACCEPT : NF_DROP,
                          verdict_mark(reason, nfq_get_nfmark(data)));
}

// Conntrack can discard a queued packet before its individual verdict returns.
static int missing_verdict(const struct nlmsghdr *h, uint16_t number) {
    if (h->nlmsg_type!=NLMSG_ERROR || h->nlmsg_len<NLMSG_LENGTH(sizeof(struct nlmsgerr)+sizeof(struct nfgenmsg))) return 0;
    struct nlmsgerr error;struct nfgenmsg family;
    memcpy(&error,NLMSG_DATA(h),sizeof(error));
    memcpy(&family,(const char *)NLMSG_DATA(h)+sizeof(error),sizeof(family));
    return error.error==-ENOENT && error.msg.nlmsg_type==((NFNL_SUBSYS_QUEUE<<8)|NFQNL_MSG_VERDICT) &&
        error.msg.nlmsg_len>=NLMSG_LENGTH(sizeof(family)) && ntohs(family.res_id)==number;
}

static int handle_datagram(struct nfq_handle *handle, char *buffer, int length, size_t *original_length, uint16_t number) {
    int remaining = length;
    struct nlmsghdr *header = (struct nlmsghdr *)buffer;
    while (NLMSG_OK(header, remaining)) {
        *original_length = 0;
        if (header->nlmsg_type == ((NFNL_SUBSYS_QUEUE << 8) | NFQNL_MSG_PACKET)) {
            struct nlattr *attributes[NFQA_MAX + 1] = {0};
            if (nfq_nlmsg_parse(header, attributes) < 0) return -1;
            if (attributes[NFQA_CAP_LEN]) {
                struct nlattr *attr = attributes[NFQA_CAP_LEN];
                uint32_t value;
                if (attr->nla_len != NLA_HDRLEN + sizeof(value)) { errno = EPROTO; return -1; }
                memcpy(&value, (const char *)attr + NLA_HDRLEN, sizeof(value));
                *original_length = ntohl(value);
            }
        }
        if (missing_verdict(header, number)) verdict_missing++;
        else if (nfq_handle_packet(handle, (char *)header, (int)header->nlmsg_len) < 0) return -1;
        /* The final message may omit alignment padding. */
        if (header->nlmsg_len == (unsigned int)remaining) return 0;
        header = NLMSG_NEXT(header, remaining);
    }
    if (remaining) { errno = EPROTO; return -1; }
    return 0;
}

int main(int argc, char **argv) {
    int check = argc == 3 && !strcmp(argv[1], "--check");
    int prefix_check = argc == 4 && !strcmp(argv[1], "--check-prefix");
    if (!check && !prefix_check && !(argc == 5 && !strcmp(argv[1], "--vm-test") && !strcmp(argv[2], "--queue")))
        fail("Usage: prefilter --check KEYFILE; --check-prefix WIRE_LENGTH KEYFILE; or --vm-test --queue NUMBER KEYFILE");
    load_keys(argv[argc - 1]);
    int result = 0;
    if (check || prefix_check) {
        unsigned char packet[65536];
        size_t n = fread(packet, 1, sizeof(packet), stdin);
        if (ferror(stdin) || n == sizeof(packet)) fail("Invalid input packet");
        size_t original_length = n;
        if (prefix_check) {
            char *end;
            errno = 0;
            unsigned long value = strtoul(argv[2], &end, 10);
            if (errno || !*argv[2] || *end || !value || value > 65535) fail("Invalid original packet length");
            original_length = value;
        }
        enum verdict reason = inspect(packet, n, original_length);
        printf("{\"accept\":%s,\"reason\":\"%s\"}\n", reason >= INIT ? "true" : "false", names[reason]);
        result = reason >= INIT ? 0 : 2;
    } else {
        if (geteuid()) fail("Queue mode needs root in a disposable VM");
        char *end;
        errno = 0;
        unsigned long number = strtoul(argv[3], &end, 10);
        if (errno || !*argv[3] || *end || number > 65535) fail("Invalid queue number");
        struct sigaction action = {0};
        action.sa_handler = signal_handler;
        sigemptyset(&action.sa_mask);
        if (sigaction(SIGINT, &action, NULL) || sigaction(SIGTERM, &action, NULL) || sigaction(SIGUSR1, &action, NULL))
            fail("Cannot install signal handlers");
        struct nfq_handle *handle = nfq_open();
        if (!handle || nfq_bind_pf(handle, AF_INET)) fail("Cannot bind NFQUEUE");
        size_t original_length = 0;
        struct nfq_q_handle *queue = nfq_create_queue(handle, (uint16_t)number, callback, &original_length);
        if (!queue || nfq_set_mode(queue, NFQNL_COPY_PACKET, copy_range) || nfq_set_queue_maxlen(queue, QUEUE_MAXLEN))
            fail("Cannot configure NFQUEUE");
        int fd = nfq_fd(handle), buffer_size = 4 * 1024 * 1024;
        /* SO_RCVBUF alone is silently clamped by net.core.rmem_max. */
        if (setsockopt(fd, SOL_SOCKET, SO_RCVBUFFORCE, &buffer_size, sizeof(buffer_size))) fail("Cannot reserve receive buffer");
        socklen_t option_size = sizeof(buffer_size);
        if (getsockopt(fd, SOL_SOCKET, SO_RCVBUF, &buffer_size, &option_size)) fail("Cannot read receive buffer");
#ifdef PREFILTER_BATCH
        queue_fd = fd;
        queue_number = (uint16_t)number;
        size_t datagram_size=copy_range+4096;
        if (datagram_size<DATAGRAM_SIZE) datagram_size=DATAGRAM_SIZE;
        char *buffers=malloc(BATCH_SIZE*datagram_size);
        if (!buffers) fail("Cannot allocate receive batch");
        struct iovec incoming_iov[BATCH_SIZE];
        struct mmsghdr incoming[BATCH_SIZE] = {0};
        for (int i = 0; i < BATCH_SIZE; i++) {
            incoming_iov[i] = (struct iovec){ .iov_base = buffers+i*datagram_size, .iov_len = datagram_size };
            incoming[i].msg_hdr.msg_iov = &incoming_iov[i];
            incoming[i].msg_hdr.msg_iovlen = 1;
        }
        int receive_batch = BATCH_SIZE;
#else
        char buffer[131072] __attribute__((aligned));
        int receive_batch = 1;
#endif
        printf("ready rcvbuf=%d queue_maxlen=%d copy_range=%u receive_batch=%d\n", buffer_size, QUEUE_MAXLEN, copy_range, receive_batch);
        fflush(stdout);
        while (!stopping) {
            if (reporting) { report(); reporting = 0; }
            TIMER_START(receive_start);
            receive_calls++;
#ifdef PREFILTER_BATCH
            int n = recvmmsg(fd, incoming, BATCH_SIZE, MSG_WAITFORONE, NULL);
#else
            ssize_t n = recv(fd, buffer, sizeof(buffer), 0);
#endif
            int receive_errno = errno;
            TIMER_STOP(receive_start, receive_ns);
            if (n < 0 && receive_errno == EINTR) continue;
            if (n < 0 && receive_errno == ENOBUFS) { netlink_enobufs++; continue; }
            if (n <= 0) { result = 1; break; }
#ifdef PREFILTER_BATCH
            received_datagrams += (unsigned int)n;
            for (int i = 0; i < n; i++) {
                if (incoming[i].msg_hdr.msg_flags & (MSG_TRUNC | MSG_CTRUNC)) {
                    errno = EMSGSIZE;
                    result = 1;
                    break;
                }
                if (handle_datagram(handle, buffers+i*datagram_size, (int)incoming[i].msg_len, &original_length, (uint16_t)number) < 0) { result = 1; break; }
            }
            if (!result && flush_verdicts() < 0) result = 1;
#else
            received_datagrams++;
            if (handle_datagram(handle, buffer, (int)n, &original_length, (uint16_t)number) < 0) result = 1;
#endif
            if (result) { perror("Queue processing failed"); break; }
        }
        report();
#ifdef PREFILTER_BATCH
        free(buffers);
#endif
        nfq_destroy_queue(queue);
        nfq_close(handle);
    }
    EVP_MAC_CTX_free(mac); EVP_MAC_free(algorithm); EVP_CIPHER_CTX_free(cipher);
    OPENSSL_cleanse(hpk, sizeof(hpk)); OPENSSL_cleanse(mac_key, sizeof(mac_key));
    return result;
}
