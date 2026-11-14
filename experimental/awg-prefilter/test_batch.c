/* SPDX-License-Identifier: MIT */
#define PREFILTER_BATCH
#define sendmsg mock_sendmsg
#define main prefilter_main
#include "prefilter.c"
#undef main
#undef sendmsg

static unsigned int mock_calls;

ssize_t mock_sendmsg(int fd, const struct msghdr *message, int flags) {
    (void)fd; (void)flags;
    const char *mode = getenv("BATCH_TEST_SEND");
    mock_calls++;
    if (mode && !strcmp(mode, "eintr") && mock_calls == 1) { errno = EINTR; return -1; }
    if (mode && (!strcmp(mode, "failure") ||
                 (!strcmp(mode, "failure-after-first") && mock_calls > 1))) {
        errno = ENOBUFS;
        return -1;
    }
    if (mode && !strcmp(mode, "short")) return 1;
    const struct sockaddr_nl *destination = message->msg_name;
    if (!destination || destination->nl_family != AF_NETLINK || destination->nl_pid) abort();
    size_t length = 0;
    for (size_t i = 0; i < message->msg_iovlen; i++) {
        const unsigned char *raw = message->msg_iov[i].iov_base;
        length += message->msg_iov[i].iov_len;
        for (size_t j = 0; j < message->msg_iov[i].iov_len; j++) printf("%02x", raw[j]);
    }
    puts("");
    return (ssize_t)length;
}

int main(int argc, char **argv) {
    if (argc != 2) return 1;
    load_keys(argv[1]);
    queue_number = 100;
    unsigned char packet[65536];
    uint32_t frame[3];
    size_t length;
    while ((length = fread(frame, 1, sizeof(frame), stdin)) != 0) {
        if (length != sizeof(frame)) return 1;
        uint32_t id = ntohl(frame[0]), original = ntohl(frame[1]), copied = ntohl(frame[2]);
        if (copied >= sizeof(packet) || fread(packet, 1, copied, stdin) != copied) return 1;
        enum verdict reason = inspect(packet, copied, original);
        const char *mark_text = getenv("BATCH_TEST_MARK");
        uint32_t mark = mark_text ? (uint32_t)strtoul(mark_text, NULL, 0) : 0;
        if (submit_verdict(NULL, id, reason >= INIT ? NF_ACCEPT : NF_DROP, verdict_mark(reason, mark)) < 0) return 1;
    }
    if (ferror(stdin) || flush_verdicts() < 0) return 1;
    return 0;
}
