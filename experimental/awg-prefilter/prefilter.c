/* SPDX-License-Identifier: MIT
 * LAB PROTOTYPE: AWG 3.1 prefilter, not client authentication.
 * shortcut: only S1-S4=12 and H1-H4=1,2,3,4; extend after interoperability tests.
 */
#define _GNU_SOURCE
#include <arpa/inet.h>
#include <errno.h>
#include <fcntl.h>
#include <linux/netfilter.h>
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
#include <unistd.h>

enum verdict { MALFORMED, HEADER, MAC, CRYPTO, INIT, RESPONSE, COOKIE, DATA, REASONS };
static const char *names[] = {"malformed", "header", "mac1", "crypto", "init", "response", "cookie", "transport"};
static uint64_t counts[REASONS], bytes;
static unsigned char hpk[32], mac_key[32];
static EVP_CIPHER_CTX *cipher;
static EVP_MAC *algorithm;
static EVP_MAC_CTX *mac;
static volatile sig_atomic_t stopping, reporting;

static void fail(const char *message) {
    fprintf(stderr, "%s\n", message);
    exit(1);
}

static void signal_handler(int number) {
    if (number == SIGUSR1) reporting = 1;
    else stopping = 1;
}

static void report(void) {
    printf("{\"bytes\":%llu", (unsigned long long)bytes);
    for (int i = 0; i < REASONS; i++)
        printf(",\"%s\":%llu", names[i], (unsigned long long)counts[i]);
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
    if (fgetc(file) != EOF || ferror(file)) fail("Unexpected key file contents");
    fclose(file);
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

static enum verdict inspect(const unsigned char *ip, size_t length) {
    if (length < 28 || ip[0] >> 4 != 4 || ip[9] != 17) return MALFORMED;
    size_t ihl = (ip[0] & 15) * 4u, total = be16(ip + 2);
    if (ihl < 20 || ihl + 8 > length || total != length || (be16(ip + 6) & 0x3fff)) return MALFORMED;
    const unsigned char *udp = ip + ihl;
    size_t udp_length = be16(udp + 4);
    if (udp_length < 8 || ihl + udp_length != total) return MALFORMED;
    const unsigned char *payload = udp + 8;
    size_t size = udp_length - 8;
    if (size < 16) return HEADER;
    unsigned char iv[16] = {0}, plain[148];
    memcpy(iv + 4, payload, 12);
    int produced = 0;
    if (!EVP_EncryptInit_ex(cipher, EVP_chacha20(), NULL, hpk, iv) ||
        !EVP_EncryptUpdate(cipher, plain, &produced, payload + 12, 4) || produced != 4) return CRYPTO;
    uint32_t type = (uint32_t)plain[0] | ((uint32_t)plain[1] << 8) |
                    ((uint32_t)plain[2] << 16) | ((uint32_t)plain[3] << 24);
    size_t fixed;
    switch (type) {
        case 1: fixed = 148; break;
        case 2: fixed = 92; break;
        case 3: return size >= 12 + 64 ? COOKIE : MALFORMED;
        case 4: return size >= 12 + 32 ? DATA : MALFORMED;
        default: return HEADER;
    }
    if (size < 12 + fixed) return MALFORMED;
    if (!EVP_EncryptUpdate(cipher, plain + 4, &produced, payload + 16, (int)fixed - 4) ||
        produced != (int)fixed - 4) return CRYPTO;
    unsigned char expected[16];
    size_t output_size = 0, wanted = sizeof(expected);
    OSSL_PARAM params[] = { OSSL_PARAM_construct_size_t(OSSL_MAC_PARAM_SIZE, &wanted), OSSL_PARAM_construct_end() };
    if (!EVP_MAC_init(mac, mac_key, 32, params) || !EVP_MAC_update(mac, plain, fixed - 32) ||
        !EVP_MAC_final(mac, expected, &output_size, sizeof(expected)) || output_size != 16) return CRYPTO;
    if (CRYPTO_memcmp(expected, plain + fixed - 32, 16)) return MAC;
    return type == 1 ? INIT : RESPONSE;
}

static int callback(struct nfq_q_handle *queue, struct nfgenmsg *message, struct nfq_data *data, void *unused) {
    (void)message; (void)unused;
    struct nfqnl_msg_packet_hdr *header = nfq_get_msg_packet_hdr(data);
    if (!header) return -1;
    unsigned char *packet = NULL;
    int length = nfq_get_payload(data, &packet);
    enum verdict reason = length > 0 ? inspect(packet, (size_t)length) : MALFORMED;
    counts[reason]++;
    if (length > 0) bytes += (unsigned int)length;
    return nfq_set_verdict(queue, ntohl(header->packet_id), reason >= INIT ? NF_ACCEPT : NF_DROP, 0, NULL);
}

int main(int argc, char **argv) {
    int check = argc == 3 && !strcmp(argv[1], "--check");
    if (!check && !(argc == 5 && !strcmp(argv[1], "--vm-test") && !strcmp(argv[2], "--queue")))
        fail("Usage: prefilter --check KEYFILE < IPV4_PACKET; or prefilter --vm-test --queue NUMBER KEYFILE");
    load_keys(argv[argc - 1]);
    int result = 0;
    if (check) {
        unsigned char packet[65536];
        size_t n = fread(packet, 1, sizeof(packet), stdin);
        if (ferror(stdin) || n == sizeof(packet)) fail("Invalid input packet");
        enum verdict reason = inspect(packet, n);
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
        struct nfq_q_handle *queue = nfq_create_queue(handle, (uint16_t)number, callback, NULL);
        if (!queue || nfq_set_mode(queue, NFQNL_COPY_PACKET, 65535) || nfq_set_queue_maxlen(queue, 2048))
            fail("Cannot configure NFQUEUE");
        int fd = nfq_fd(handle), buffer_size = 4 * 1024 * 1024;
        /* SO_RCVBUF alone is silently clamped by net.core.rmem_max. */
        if (setsockopt(fd, SOL_SOCKET, SO_RCVBUFFORCE, &buffer_size, sizeof(buffer_size))) fail("Cannot reserve receive buffer");
        socklen_t option_size = sizeof(buffer_size);
        if (getsockopt(fd, SOL_SOCKET, SO_RCVBUF, &buffer_size, &option_size)) fail("Cannot read receive buffer");
        unsigned char buffer[131072] __attribute__((aligned));
        printf("ready rcvbuf=%d queue_maxlen=2048\n", buffer_size); fflush(stdout);
        while (!stopping) {
            if (reporting) { report(); reporting = 0; }
            ssize_t n = recv(fd, buffer, sizeof(buffer), 0);
            if (n < 0 && errno == EINTR) continue;
            if (n < 0 && errno == ENOBUFS) continue;
            if (n <= 0 || nfq_handle_packet(handle, (char *)buffer, (int)n) < 0) { result = 1; break; }
        }
        report();
        nfq_destroy_queue(queue);
        nfq_close(handle);
    }
    EVP_MAC_CTX_free(mac); EVP_MAC_free(algorithm); EVP_CIPHER_CTX_free(cipher);
    OPENSSL_cleanse(hpk, sizeof(hpk)); OPENSSL_cleanse(mac_key, sizeof(mac_key));
    return result;
}
