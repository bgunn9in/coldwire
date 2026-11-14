#define WIN32_LEAN_AND_MEAN
#ifdef NDEBUG
#error "This lab helper requires assertions enabled"
#endif
#include <winsock2.h>
#include <ws2tcpip.h>
#include <windows.h>
#include <assert.h>
#include <inttypes.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define PEERS 4
#define MACS 64
#define INPUT_CAP 262144u
#define OUTPUT_CAP (4u * 1024u * 1024u)
#define FRAME_CAP 65536u
#define BINS 4096u

typedef struct {
    SOCKET fd;
    unsigned char *input, *output, mac[6];
    size_t input_len, head, pending;
    int active, has_mac;
    uint64_t pending_since, frames_in, bytes_sent, peak_pending;
    uint64_t short_sends, blocked_sends, max_pending_age;
} Peer;

typedef struct { unsigned char mac[6]; int used, peer; uint64_t age; } Mac;
typedef struct { uint64_t bucket, count, first_ns; } Bin;
static Peer peers[PEERS];
static Mac macs[MACS];
static Bin bins[BINS];
static size_t bin_count;
static uint64_t frequency, frames, copies, drops, peak_pending, max_pending_age;
static uint64_t noise_frames, noise_first_ns, noise_last_ns, short_sends, blocked_sends;
static uint64_t malformed_connections, rejected_connections;
static volatile LONG stopping;

static uint64_t now_ns(void) {
    LARGE_INTEGER value;
    assert(QueryPerformanceCounter(&value) && value.QuadPart >= 0);
    uint64_t ticks = (uint64_t)value.QuadPart;
    return ticks / frequency * UINT64_C(1000000000) +
           ticks % frequency * UINT64_C(1000000000) / frequency;
}

static uint64_t cpu_ns(void) {
    FILETIME created, exited, kernel, user;
    assert(GetProcessTimes(GetCurrentProcess(), &created, &exited, &kernel, &user));
    uint64_t a = (uint64_t)kernel.dwHighDateTime << 32 | kernel.dwLowDateTime;
    uint64_t b = (uint64_t)user.dwHighDateTime << 32 | user.dwLowDateTime;
    return (a + b) * 100;
}

static uint32_t be32(const unsigned char *p) {
    return (uint32_t)p[0] << 24 | (uint32_t)p[1] << 16 | (uint32_t)p[2] << 8 | p[3];
}

static unsigned be16(const unsigned char *p) { return (unsigned)p[0] << 8 | p[1]; }

static void initialize(void) {
    LARGE_INTEGER value;
    assert(QueryPerformanceFrequency(&value) && value.QuadPart > 0);
    frequency = (uint64_t)value.QuadPart;
    assert(frequency <= UINT64_MAX / UINT64_C(1000000000));
    for (int i = 0; i < PEERS; i++) {
        peers[i].fd = INVALID_SOCKET;
        peers[i].input = malloc(INPUT_CAP);
        peers[i].output = malloc(OUTPUT_CAP);
        assert(peers[i].input && peers[i].output);
    }
}

static void disconnect_peer(int index) {
    Peer *p = &peers[index];
    if (p->fd != INVALID_SOCKET) closesocket(p->fd);
    p->fd = INVALID_SOCKET;
    p->active = p->has_mac = 0;
    p->input_len = p->head = p->pending = 0;
    for (int i = 0; i < MACS; i++) if (macs[i].used && macs[i].peer == index) macs[i].used = 0;
}

static int lookup(const unsigned char *mac) {
    for (int i = 0; i < MACS; i++)
        if (macs[i].used && !memcmp(macs[i].mac, mac, 6)) return macs[i].peer;
    return -1;
}

static void learn(const unsigned char *mac, int peer) {
    int slot = -1, oldest = 0;
    for (int i = 0; i < MACS; i++) {
        if (macs[i].used && !memcmp(macs[i].mac, mac, 6)) { slot = i; break; }
        if (!macs[i].used) slot = i;
        if (macs[i].age < macs[oldest].age) oldest = i;
    }
    if (slot < 0) slot = oldest;
    macs[slot].used = 1; macs[slot].peer = peer; macs[slot].age = frames;
    memcpy(macs[slot].mac, mac, 6);
}

static int enqueue(Peer *p, const unsigned char *data, size_t size) {
    assert(p->pending <= OUTPUT_CAP);
    if (size > OUTPUT_CAP - p->pending) { drops++; return 0; }
    if (!p->pending) p->pending_since = now_ns();
    size_t tail = (p->head + p->pending) % OUTPUT_CAP;
    size_t first = size < OUTPUT_CAP - tail ? size : OUTPUT_CAP - tail;
    memcpy(p->output + tail, data, first);
    memcpy(p->output, data + first, size - first);
    p->pending += size;
    if (p->pending > p->peak_pending) p->peak_pending = p->pending;
    if (p->pending > peak_pending) peak_pending = p->pending;
    return 1;
}

static void record_noise(uint64_t stamp) {
    uint64_t bucket = stamp / UINT64_C(100000000);
    if (!bin_count || bins[bin_count - 1].bucket != bucket) {
        if (bin_count) assert(bucket > bins[bin_count - 1].bucket);
        if (bin_count == BINS) {
            /* Observation history must not terminate Ethernet forwarding. */
            memmove(bins, bins + 1, (BINS - 1) * sizeof(*bins));
            bin_count--;
        }
        bins[bin_count++] = (Bin){bucket, 0, stamp};
    }
    bins[bin_count - 1].count++; noise_frames++; noise_last_ns = stamp;
    if (!noise_first_ns) noise_first_ns = stamp;
}

static void observe_noise(const unsigned char *f, uint32_t size) {
    static const unsigned char addresses[] = {192, 168, 76, 40, 192, 168, 76, 10};
    if (size < 46 || f[16] != 8 || f[17] || f[18] != 0x45 || f[27] != 17 ||
        memcmp(f + 30, addresses, 8) ||
        be16(f + 40) != 32497 || be16(f + 42) != 264) return;
    record_noise(now_ns());
}

static void forward_frame(int source, const unsigned char *f, uint32_t size) {
    if (size < 14) return;
    frames++; peers[source].frames_in++;
    memcpy(peers[source].mac, f + 10, 6); peers[source].has_mac = 1;
    learn(f + 10, source); observe_noise(f, size);
    int destination = f[4] & 1 ? -1 : lookup(f + 4);
    for (int i = 0; i < PEERS; i++)
        if (i != source && peers[i].active && (destination < 0 || destination == i))
            if (enqueue(&peers[i], f, (size_t)size + 4)) copies++;
}

static void parse_input(int index) {
    Peer *p = &peers[index];
    size_t offset = 0;
    while (p->input_len - offset >= 4) {
        uint32_t size = be32(p->input + offset);
        if (size > FRAME_CAP) { malformed_connections++; disconnect_peer(index); return; }
        if (p->input_len - offset < (size_t)size + 4) break;
        forward_frame(index, p->input + offset, size);
        offset += (size_t)size + 4;
    }
    p->input_len -= offset;
    if (offset) memmove(p->input, p->input + offset, p->input_len);
}

static void nullable(FILE *f, uint64_t value) {
    if (value) fprintf(f, "%" PRIu64, value); else fputs("null", f);
}

static void write_stats(const char *path) {
    char temporary[MAX_PATH];
    assert(strlen(path) + 5 < sizeof(temporary));
    snprintf(temporary, sizeof(temporary), "%s.tmp", path);
    FILE *f = fopen(temporary, "wb");
    assert(f);
    unsigned ports = 0, learned = 0;
    for (int i = 0; i < PEERS; i++) ports += peers[i].active != 0;
    for (int i = 0; i < MACS; i++) learned += macs[i].used != 0;
    fprintf(f, "{\"version\":\"native-c-v1-observed\",\"tcp_nodelay\":true,"
            "\"frames\":%" PRIu64 ",\"copies\":%" PRIu64 ",\"dropped\":%" PRIu64 ","
            "\"peak_pending_bytes\":%" PRIu64 ",\"max_pending_age_ns\":%" PRIu64 ","
            "\"short_sends\":%" PRIu64 ",\"blocked_sends\":%" PRIu64 ","
            "\"malformed_connections\":%" PRIu64 ",\"rejected_connections\":%" PRIu64 ","
            "\"ports\":%u,\"learned_macs\":%u,\"process_cpu_ns\":%" PRIu64 ",\"snapshot_ns\":%" PRIu64 ","
            "\"noise_frames\":%" PRIu64 ",\"noise_first_ns\":",
            frames, copies, drops, peak_pending, max_pending_age, short_sends, blocked_sends,
            malformed_connections, rejected_connections, ports, learned, cpu_ns(), now_ns(), noise_frames);
    nullable(f, noise_first_ns); fputs(",\"noise_last_ns\":", f); nullable(f, noise_last_ns);
    fputs(",\"noise_bins_100ms\":{", f);
    for (size_t i = 0; i < bin_count; i++)
        fprintf(f, "%s\"%" PRIu64 "\":%" PRIu64, i ? "," : "", bins[i].bucket, bins[i].count);
    fputs("},\"noise_bin_first_ns\":{", f);
    for (size_t i = 0; i < bin_count; i++)
        fprintf(f, "%s\"%" PRIu64 "\":%" PRIu64, i ? "," : "", bins[i].bucket, bins[i].first_ns);
    fputs("},\"port_stats\":[", f);
    int comma = 0;
    for (int i = 0; i < PEERS; i++) if (peers[i].active) {
        Peer *p = &peers[i];
        fprintf(f, "%s{\"source_mac\":", comma++ ? "," : "");
        if (p->has_mac) fprintf(f, "\"%02x%02x%02x%02x%02x%02x\"", p->mac[0], p->mac[1], p->mac[2], p->mac[3], p->mac[4], p->mac[5]);
        else fputs("null", f);
        fprintf(f, ",\"frames_in\":%" PRIu64 ",\"bytes_sent\":%" PRIu64 ",\"short_sends\":%" PRIu64
                ",\"blocked_sends\":%" PRIu64 ",\"peak_pending_bytes\":%" PRIu64 ",\"max_pending_age_ns\":%" PRIu64 "}",
                p->frames_in, p->bytes_sent, p->short_sends, p->blocked_sends, p->peak_pending, p->max_pending_age);
    }
    fputs("]}\n", f);
    assert(!ferror(f)); assert(!fclose(f));
    for (int attempt = 0; !MoveFileExA(temporary, path, MOVEFILE_REPLACE_EXISTING); attempt++) {
        DWORD error = GetLastError();
        assert(attempt < 20 && (error == ERROR_SHARING_VIOLATION || error == ERROR_ACCESS_DENIED));
        Sleep(1);
    }
}

static void self_test(void) {
    Peer *p = &peers[0];
    p->head = OUTPUT_CAP - 2;
    const unsigned char bytes[] = {1, 2, 3, 4};
    assert(enqueue(p, bytes, 4));
    assert(p->output[OUTPUT_CAP-2] == 1 && p->output[OUTPUT_CAP-1] == 2 && p->output[0] == 3 && p->output[1] == 4);
    p->pending = OUTPUT_CAP;
    assert(!enqueue(p, bytes, 1) && p->pending == OUTPUT_CAP && drops == 1);
    disconnect_peer(0);
    for (unsigned i = 0; i < MACS + 4; i++) {
        unsigned char mac[] = {2, 0, 0, 0, 0, (unsigned char)i};
        frames++; learn(mac, 1); assert(lookup(mac) == 1);
    }
    disconnect_peer(1);
    for (int i = 0; i < MACS; i++) assert(!macs[i].used);
    peers[0].active = 1; peers[1].active = 1;
    const unsigned char frame[] = {0,0,0,14, 2,0,0,0,0,1, 2,0,0,0,0,2, 8,0};
    memcpy(peers[0].input, frame, 3); peers[0].input_len = 3; parse_input(0);
    assert(peers[0].input_len == 3 && !peers[1].pending);
    memcpy(peers[0].input + 3, frame + 3, sizeof(frame)-3); peers[0].input_len = sizeof(frame); parse_input(0);
    assert(!peers[0].input_len && peers[1].pending == sizeof(frame));
    const unsigned char invalid[] = {0,1,0,1};
    memcpy(peers[0].input, invalid, 4); peers[0].input_len = 4; parse_input(0);
    assert(!peers[0].active && malformed_connections == 1);
    for (uint64_t i = 1; i <= BINS + 3; i++) record_noise(i * UINT64_C(100000000));
    assert(bin_count == BINS && bins[0].bucket == 4 && bins[BINS-1].bucket == BINS + 3);
    record_noise((BINS + 3) * UINT64_C(100000000) + 1);
    assert(bin_count == BINS && bins[BINS-1].count == 2 && noise_frames == BINS + 4);
    puts("PASS ring wrap/bounds, MAC eviction/disconnect, incremental parsing and rolling noise history");
}

static BOOL WINAPI control(DWORD event) {
    if (event == CTRL_C_EVENT || event == CTRL_BREAK_EVENT || event == CTRL_CLOSE_EVENT) {
        InterlockedExchange(&stopping, 1); return TRUE;
    }
    return FALSE;
}

int main(int argc, char **argv) {
    initialize();
    if (argc == 2 && !strcmp(argv[1], "--self-test")) { self_test(); return 0; }
    if (argc != 3) { fputs("Usage: native-switch PORT STATS_JSON\n", stderr); return 2; }
    char *end;
    long port = strtol(argv[1], &end, 10);
    if (!*argv[1] || *end || port < 1024 || port > 65535 || strlen(argv[2])+5 >= MAX_PATH) return 2;
    WSADATA data;
    assert(!WSAStartup(MAKEWORD(2,2), &data));
    SOCKET listener = socket(AF_INET, SOCK_STREAM, IPPROTO_TCP);
    assert(listener != INVALID_SOCKET);
    BOOL exclusive = TRUE;
    assert(!setsockopt(listener, SOL_SOCKET, SO_EXCLUSIVEADDRUSE, (const char *)&exclusive, sizeof(exclusive)));
    struct sockaddr_in address = {0};
    address.sin_family = AF_INET; address.sin_port = htons((u_short)port); address.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
    assert(!bind(listener, (struct sockaddr *)&address, sizeof(address)) && !listen(listener, PEERS));
    u_long nonblocking = 1;
    assert(!ioctlsocket(listener, FIONBIO, &nonblocking));
    assert(SetConsoleCtrlHandler(control, TRUE));
    puts("ready"); fflush(stdout);
    uint64_t last_stats = 0;
    while (!stopping) {
        fd_set reads, writes;
        FD_ZERO(&reads); FD_ZERO(&writes); FD_SET(listener, &reads);
        for (int i = 0; i < PEERS; i++) if (peers[i].active) {
            FD_SET(peers[i].fd, &reads);
            if (peers[i].pending) FD_SET(peers[i].fd, &writes);
        }
        struct timeval timeout = {0, 50000};
        int ready = select(0, &reads, &writes, NULL, &timeout);
        assert(ready != SOCKET_ERROR);
        if (FD_ISSET(listener, &reads)) {
            SOCKET fd = accept(listener, NULL, NULL);
            if (fd != INVALID_SOCKET) {
                int slot = 0;
                while (slot < PEERS && peers[slot].active) slot++;
                if (slot == PEERS) { rejected_connections++; closesocket(fd); }
                else {
                    BOOL enabled = TRUE;
                    assert(!setsockopt(fd, IPPROTO_TCP, TCP_NODELAY, (const char *)&enabled, sizeof(enabled)));
                    assert(!ioctlsocket(fd, FIONBIO, &nonblocking));
                    peers[slot].fd = fd; peers[slot].active = 1;
                }
            } else assert(WSAGetLastError() == WSAEWOULDBLOCK);
        }
        for (int i = 0; i < PEERS; i++) if (peers[i].active) {
            Peer *p = &peers[i];
            if (FD_ISSET(p->fd, &reads)) {
                size_t room = INPUT_CAP - p->input_len;
                assert(room);
                int amount = room < 131072u ? (int)room : 131072;
                int count = recv(p->fd, (char *)p->input+p->input_len, amount, 0);
                if (!count || (count == SOCKET_ERROR && WSAGetLastError() != WSAEWOULDBLOCK)) { disconnect_peer(i); continue; }
                if (count > 0) { p->input_len += (size_t)count; parse_input(i); }
            }
            if (p->active && p->pending && FD_ISSET(p->fd, &writes)) {
                size_t amount = p->pending < OUTPUT_CAP-p->head ? p->pending : OUTPUT_CAP-p->head;
                int count = send(p->fd, (const char *)p->output+p->head, (int)amount, 0);
                if (count == SOCKET_ERROR && WSAGetLastError() == WSAEWOULDBLOCK) { blocked_sends++; p->blocked_sends++; continue; }
                if (count <= 0) { disconnect_peer(i); continue; }
                if ((size_t)count < amount) { short_sends++; p->short_sends++; }
                uint64_t age = now_ns()-p->pending_since;
                if (age > max_pending_age) max_pending_age = age;
                if (age > p->max_pending_age) p->max_pending_age = age;
                p->bytes_sent += (uint64_t)count;
                p->head = (p->head+(size_t)count) % OUTPUT_CAP; p->pending -= (size_t)count;
            }
        }
        uint64_t stamp = now_ns();
        if (stamp-last_stats >= UINT64_C(1000000000)) { write_stats(argv[2]); last_stats = stamp; }
    }
    write_stats(argv[2]);
    for (int i = 0; i < PEERS; i++) { disconnect_peer(i); free(peers[i].input); free(peers[i].output); }
    closesocket(listener); WSACleanup();
    return 0;
}
