#define WIN32_LEAN_AND_MEAN
#ifdef NDEBUG
#error "This lab helper requires assertions enabled"
#endif
#include <winsock2.h>
#include <mstcpip.h>
#include <ws2tcpip.h>
#include <afunix.h>
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
#define TAP_HEADER_BYTES 96u
#define BINS 4096u

typedef struct {
    SOCKET fd;
    unsigned char *input, *output, mac[6];
    size_t input_len, head, pending;
    int active, has_mac;
    uint64_t pending_since, frames_in, bytes_sent, peak_pending;
    uint64_t short_sends, blocked_sends, max_pending_age;
    uint64_t output_drops, last_progress, max_progress_gap, tcp_sample_ns;
    uint64_t drop_start, drop_end, episode_drops, episode_noise, dropped_noise;
} Peer;

typedef struct { unsigned char mac[6]; int used, peer; uint64_t age; } Mac;
typedef struct { uint64_t bucket, count, first_ns; } Bin;
static Peer peers[PEERS];
static Mac macs[MACS];
static Bin bins[BINS];
static size_t bin_count;
static uint64_t frequency, frames, copies, drops, peak_pending, max_pending_age;
static uint64_t noise_frames, noise_first_ns, noise_last_ns, short_sends, blocked_sends;
static uint64_t noise_source_frames[16];
static uint64_t malformed_connections, rejected_connections;
static volatile LONG stopping;
static BOOL use_unix;

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

static uint64_t queued_send_gap(const Peer *p, uint64_t now) {
    uint64_t current = p->pending ? now - p->last_progress : 0;
    return current > p->max_progress_gap ? current : p->max_progress_gap;
}

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
    *p = (Peer){.fd = INVALID_SOCKET, .input = p->input, .output = p->output};
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
    if (size > OUTPUT_CAP - p->pending) {
        drops++;
        p->output_drops++;
        return 0;
    }
    if (!p->pending) p->pending_since = p->last_progress = now_ns();
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

static int observe_noise(const unsigned char *f, uint32_t size) {
    static const unsigned char prefix[] = {192, 168, 76}, destination[] = {192, 168, 76, 10};
    if (size < 46 || f[16] != 8 || f[17] || f[18] != 0x45 || f[27] != 17 ||
        memcmp(f + 30, prefix, 3) || f[33] < 40 || f[33] > 55 ||
        memcmp(f + 34, destination, 4) ||
        be16(f + 40) != 32497 || be16(f + 42) != 264) return 0;
    noise_source_frames[f[33] - 40]++;
    record_noise(now_ns());
    return 1;
}

/* The optional tap records only the fixture's tunnel and control tuples. */
static const char *tap_dir;
static int tap_return_headers;
static FILE *tap_file;
static unsigned char tap_buffer[1024 * 1024];
static uint64_t tap_until, tap_sequence, tap_frames, tap_errors, tap_closed;

struct tap_header { uint32_t magic; uint16_t major, minor; uint32_t zone, accuracy, snaplen, link; };
struct tap_packet { uint32_t seconds, micros, included, original; };
_Static_assert(sizeof(struct tap_header) == 24 && sizeof(struct tap_packet) == 16, "PCAP layout");

static unsigned tap_select(const unsigned char *p, uint32_t size) {
    static const unsigned char lab[] = {192, 168, 76};
    if (size < 42 || be16(p + 12) != 0x0800 || p[14] >> 4 != 4) return 0;
    unsigned ihl = (p[14] & 15) * 4;
    if (ihl < 20 || size < 14 + ihl + 8 || (be16(p + 20) & 0x3fff) ||
        memcmp(p + 26, lab, 3) || memcmp(p + 30, lab, 3)) return 0;
    unsigned source = p[29], target = p[33];
    unsigned sport = be16(p + 14 + ihl), dport = be16(p + 16 + ihl);
    if (p[23] == 6 && ((source == 10 && target == 20) || (source == 20 && target == 10)) &&
        (sport == 39101 || dport == 39101)) return 1;
    if (p[23] != 17) return 0;
    if ((source == 30 || source == 31) && target == 10 && dport == 32497)
        return sport == 42501 ? 3 : 1;
    if (tap_return_headers && source == 10 && (target == 30 || target == 31) &&
        sport == 32497) return 1;
    return (source == 10 && target == 20 && dport == 32497) ||
           (source == 20 && target == 10 && sport == 32497);
}

static void tap_close(void) {
    if (!tap_file) return;
    if (fclose(tap_file)) tap_errors++;
    tap_file = NULL;
    tap_closed++;
}

static void tap_tick(uint64_t now) {
    if (tap_file && now >= tap_until) tap_close();
}

static void tap_frame(const unsigned char *p, uint32_t size) {
    if (!tap_dir) return;
    uint64_t now = now_ns();
    tap_tick(now);
    unsigned selected = tap_select(p, size);
    uint32_t snaplen = tap_return_headers ? TAP_HEADER_BYTES : FRAME_CAP;
    if (!tap_file && now >= tap_until && (selected & 2)) {
        char path[MAX_PATH];
        tap_until = now + UINT64_C(8000000000);
        tap_sequence++;
        int length = snprintf(path, sizeof(path), "%s/tap-%04" PRIu64 ".pcap", tap_dir, tap_sequence);
        if (length < 0 || (size_t)length >= sizeof(path) || !(tap_file = fopen(path, "wbx"))) {
            tap_errors++;
            return;
        }
        const struct tap_header header = {0xa1b2c3d4, 2, 4, 0, 0, snaplen, 1};
        if (setvbuf(tap_file, (char *)tap_buffer, _IOFBF, sizeof(tap_buffer)) ||
            fwrite(&header, sizeof(header), 1, tap_file) != 1) {
            tap_errors++;
            tap_close();
            return;
        }
    }
    if (!tap_file || !selected) return;
    FILETIME ft;
    GetSystemTimePreciseAsFileTime(&ft);
    uint64_t ticks = (uint64_t)ft.dwHighDateTime << 32 | ft.dwLowDateTime;
    uint64_t micros = (ticks - UINT64_C(116444736000000000)) / 10;
    uint32_t captured = size < snaplen ? size : snaplen;
    const struct tap_packet record = {(uint32_t)(micros / 1000000),
                                      (uint32_t)(micros % 1000000), captured, size};
    if (fwrite(&record, sizeof(record), 1, tap_file) != 1 ||
        fwrite(p, captured, 1, tap_file) != 1) {
        tap_errors++;
        tap_close();
        return;
    }
    tap_frames++;
}

static void forward_frame(int source, const unsigned char *f, uint32_t size) {
    if (size < 14) return;
    frames++; peers[source].frames_in++;
    memcpy(peers[source].mac, f + 10, 6); peers[source].has_mac = 1;
    learn(f + 10, source);
    int noise = observe_noise(f, size);
    tap_frame(f + 4, size);
    int destination = f[4] & 1 ? -1 : lookup(f + 4);
    for (int i = 0; i < PEERS; i++) {
        Peer *p = &peers[i];
        if (i == source || !p->active || (destination >= 0 && destination != i)) continue;
        if (enqueue(p, f, (size_t)size + 4)) {
            copies++;
            continue;
        }
        p->drop_end = now_ns();
        if (!p->episode_drops) p->drop_start = p->drop_end;
        p->episode_drops++;
        p->episode_noise += noise;
        p->dropped_noise += noise;
    }
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

#ifdef SIO_TCP_INFO
static void sample_backpressure(uint64_t now) {
    for (int i = 0; i < PEERS; i++) {
        Peer *p = &peers[i];
        if (!p->active || !p->pending || now - p->last_progress < 50000000 ||
            now - p->tcp_sample_ns < 100000000) continue;
        p->tcp_sample_ns = now;
        ULONG version = 0;
        TCP_INFO_v0 info = {0};
        DWORD written = 0;
        int status = WSAIoctl(p->fd, SIO_TCP_INFO, &version, sizeof(version),
                              &info, sizeof(info), &written, NULL, NULL);
        int error = status ? WSAGetLastError() : written < sizeof(info) ? WSAEINVAL : 0;
        fprintf(stderr, "CW44 tcp now=%" PRIu64
                " mac=%02x%02x%02x%02x%02x%02x pending=%zu gap=%" PRIu64
                " drops=%" PRIu64 " error=%d sent_window=%lu flight=%lu"
                " bytes_out=%" PRIu64 " retrans=%lu timeout_episodes=%lu\n",
                now, p->mac[0], p->mac[1], p->mac[2], p->mac[3], p->mac[4], p->mac[5],
                p->pending, now - p->last_progress, p->output_drops, error,
                info.SndWnd, info.BytesInFlight, (uint64_t)info.BytesOut,
                info.BytesRetrans, info.TimeoutEpisodes);
    }
}
#endif

static void log_loss_recovery(Peer *p, uint64_t stamp) {
    if (!p->episode_drops) return;
    fprintf(stderr, "CW46 loss mac=%02x%02x%02x%02x%02x%02x first=%" PRIu64
            " last=%" PRIu64 " recovered=%" PRIu64 " gap=%" PRIu64
            " age=%" PRIu64 " pending=%zu noise=%" PRIu64 " other=%" PRIu64 "\n",
            p->mac[0], p->mac[1], p->mac[2], p->mac[3], p->mac[4], p->mac[5],
            p->drop_start, p->drop_end, stamp, stamp - p->last_progress,
            stamp - p->pending_since, p->pending, p->episode_noise, p->episode_drops - p->episode_noise);
    p->episode_drops = p->episode_noise = 0;
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
    fprintf(f, "{\"version\":\"native-c-v1-observed\",\"tcp_nodelay\":%s,"
            "\"frames\":%" PRIu64 ",\"copies\":%" PRIu64 ",\"dropped\":%" PRIu64 ","
            "\"peak_pending_bytes\":%" PRIu64 ",\"max_pending_age_ns\":%" PRIu64 ","
            "\"short_sends\":%" PRIu64 ",\"blocked_sends\":%" PRIu64 ","
            "\"malformed_connections\":%" PRIu64 ",\"rejected_connections\":%" PRIu64 ","
            "\"ports\":%u,\"learned_macs\":%u,\"process_cpu_ns\":%" PRIu64 ",\"snapshot_ns\":%" PRIu64 ","
            "\"noise_frames\":%" PRIu64 ",\"noise_first_ns\":",
            use_unix ? "false" : "true", frames, copies, drops, peak_pending, max_pending_age, short_sends, blocked_sends,
            malformed_connections, rejected_connections, ports, learned, cpu_ns(), now_ns(), noise_frames);
    nullable(f, noise_first_ns); fputs(",\"noise_last_ns\":", f); nullable(f, noise_last_ns);
    fputs(",\"noise_source_frames\":{", f);
    for (int i = 0; i < 16; i++)
        fprintf(f, "%s\"192.168.76.%d\":%" PRIu64, i ? "," : "", 40 + i, noise_source_frames[i]);
    fputs("},\"noise_bins_100ms\":{", f);
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
        fprintf(f, ",\"output_drops\":%" PRIu64 ",\"noise_output_drops\":%" PRIu64
                ",\"max_queued_send_gap_ns\":%" PRIu64,
                p->output_drops, p->dropped_noise, queued_send_gap(p, now_ns()));
        fprintf(f, ",\"frames_in\":%" PRIu64 ",\"bytes_sent\":%" PRIu64 ",\"short_sends\":%" PRIu64
                ",\"blocked_sends\":%" PRIu64 ",\"peak_pending_bytes\":%" PRIu64 ",\"max_pending_age_ns\":%" PRIu64 "}",
                p->frames_in, p->bytes_sent, p->short_sends, p->blocked_sends, p->peak_pending, p->max_pending_age);
    }
    fprintf(f, "],\"tap_sequence\":%" PRIu64 ",\"tap_frames\":%" PRIu64
            ",\"tap_errors\":%" PRIu64 ",\"tap_closed\":%" PRIu64 "}\n",
            tap_sequence, tap_frames, tap_errors, tap_closed);
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
    assert(!enqueue(p, bytes, 1) && p->pending == OUTPUT_CAP && drops == 1 && p->output_drops == 1);
    assert(peers[1].output_drops == 0);
    p->pending_since = 10;
    p->last_progress = 30;
    p->max_progress_gap = 20;
    assert(queued_send_gap(p, 40) == 20 && queued_send_gap(p, 60) == 30);
    disconnect_peer(0);
    assert(!p->output_drops && !p->last_progress && !p->max_progress_gap);
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
    unsigned char fixture[302] = {0};
    fixture[4] = 2; fixture[10] = 4;
    fixture[16] = 8; fixture[18] = 0x45; fixture[27] = 17;
    memcpy(fixture + 30, "\xc0\xa8\x4c\x28\xc0\xa8\x4c\x0a", 8);
    fixture[38] = 42501 >> 8; fixture[39] = 42501 & 255;
    fixture[40] = 32497 >> 8; fixture[41] = 32497 & 255;
    fixture[42] = 1; fixture[43] = 8;
    peers[1].pending = OUTPUT_CAP;
    forward_frame(0, fixture, 298);
    fixture[33] = 31;
    assert(tap_select(fixture + 4, 298) == 3 && !tap_select(fixture + 4, 33));
    forward_frame(0, fixture, 298);
    assert(peers[1].output_drops == 2 && peers[1].dropped_noise == 1);
    assert(peers[1].episode_drops == 2 && peers[1].episode_noise == 1);
    disconnect_peer(1);
    assert(!peers[1].dropped_noise && !peers[1].episode_drops);
    fixture[33] = 10;
    fixture[37] = 31;
    fixture[38] = 32497 >> 8; fixture[39] = 32497 & 255;
    fixture[40] = 42501 >> 8; fixture[41] = 42501 & 255;
    assert(!tap_select(fixture + 4, 298));
    tap_return_headers = 1;
    assert(tap_select(fixture + 4, 298) == 1);
    fixture[37] = 30;
    assert(tap_select(fixture + 4, 298) == 1);
    fixture[37] = 32;
    assert(!tap_select(fixture + 4, 298));
    tap_return_headers = 0;
    bin_count = noise_frames = noise_first_ns = noise_last_ns = 0;
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
    if (argc < 3 || argc > 5 || (argc == 5 && strcmp(argv[4], "--return-headers"))) {
        fputs("Usage: native-switch PORT|unix:PATH STATS_JSON "
              "[TAP_DIRECTORY [--return-headers]]\n", stderr);
        return 2;
    }
    tap_return_headers = argc == 5;
    if (argc >= 4) {
        DWORD attributes = GetFileAttributesA(argv[3]);
        if (strlen(argv[3]) + 32 >= MAX_PATH || attributes == INVALID_FILE_ATTRIBUTES ||
            !(attributes & FILE_ATTRIBUTE_DIRECTORY)) {
            fputs("TAP_DIRECTORY must be an existing local directory with a short path\n", stderr);
            return 2;
        }
        tap_dir = argv[3];
    }
    char *end;
    use_unix = !strncmp(argv[1], "unix:", 5);
    const char *path = argv[1] + (use_unix ? 5 : 0);
    long port = use_unix ? 0 : strtol(path, &end, 10);
    if (!*path || strlen(argv[2]) + 5 >= MAX_PATH) return 2;
    if (!use_unix && (*end || port < 1024 || port > 65535)) return 2;
    WSADATA data;
    assert(!WSAStartup(MAKEWORD(2,2), &data));
    SOCKET listener = socket(use_unix ? AF_UNIX : AF_INET, SOCK_STREAM, 0);
    assert(listener != INVALID_SOCKET);
    if (use_unix) {
        struct sockaddr_un addr = { .sun_family = AF_UNIX };
        if (strlen(path) >= sizeof(addr.sun_path)) return 2;
        strcpy(addr.sun_path, path);
        if (bind(listener, (struct sockaddr *)&addr, sizeof(addr))) {
            fprintf(stderr, "AF_UNIX bind failed: %d\n", WSAGetLastError());
            return 1;
        }
    } else {
        BOOL exclusive = TRUE;
        assert(!setsockopt(listener, SOL_SOCKET, SO_EXCLUSIVEADDRUSE, (const char *)&exclusive, sizeof(exclusive)));
        struct sockaddr_in address = {0};
        address.sin_family = AF_INET; address.sin_port = htons((u_short)port);
        address.sin_addr.s_addr = htonl(INADDR_LOOPBACK);
        assert(!bind(listener, (struct sockaddr *)&address, sizeof(address)));
    }
    assert(!listen(listener, PEERS));
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
        uint64_t poll_start = now_ns();
        int ready = select(0, &reads, &writes, NULL, &timeout);
        assert(ready != SOCKET_ERROR);
        uint64_t work_start = now_ns();
        if (work_start - poll_start >= 75000000)
            fprintf(stderr, "CW46 select start=%" PRIu64 " end=%" PRIu64 " ready=%d\n",
                    poll_start, work_start, ready);
        if (FD_ISSET(listener, &reads)) {
            SOCKET fd = accept(listener, NULL, NULL);
            if (fd != INVALID_SOCKET) {
                int slot = 0;
                while (slot < PEERS && peers[slot].active) slot++;
                if (slot == PEERS) { rejected_connections++; closesocket(fd); }
                else {
                    BOOL enabled = TRUE;
                    if (!use_unix) {
                        assert(!setsockopt(fd, IPPROTO_TCP, TCP_NODELAY,
                                           (const char *)&enabled, sizeof(enabled)));
                    }
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
                uint64_t stamp = now_ns();
                log_loss_recovery(p, stamp);
                p->max_progress_gap = queued_send_gap(p, stamp);
                p->last_progress = stamp;
                uint64_t age = stamp - p->pending_since;
                if (age > max_pending_age) max_pending_age = age;
                if (age > p->max_pending_age) p->max_pending_age = age;
                p->bytes_sent += (uint64_t)count;
                p->head = (p->head+(size_t)count) % OUTPUT_CAP; p->pending -= (size_t)count;
            }
        }
        uint64_t stamp = now_ns();
        tap_tick(stamp);
#ifdef SIO_TCP_INFO
        if (!use_unix) sample_backpressure(stamp);
#endif
        if (stamp - work_start >= 50000000)
            fprintf(stderr, "CW46 forward start=%" PRIu64 " end=%" PRIu64 "\n", work_start, stamp);
        if (stamp - last_stats >= UINT64_C(1000000000)) {
            uint64_t started = now_ns();
            write_stats(argv[2]);
            uint64_t finished = now_ns();
            if (finished - started >= 20000000)
                fprintf(stderr, "CW46 stats start=%" PRIu64 " end=%" PRIu64 "\n", started, finished);
            last_stats = stamp;
        }
    }
    tap_close();
    write_stats(argv[2]);
    for (int i = 0; i < PEERS; i++) { disconnect_peer(i); free(peers[i].input); free(peers[i].output); }
    closesocket(listener); WSACleanup();
    return 0;
}
