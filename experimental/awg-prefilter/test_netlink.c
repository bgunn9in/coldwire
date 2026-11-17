/* SPDX-License-Identifier: MIT */
#define _GNU_SOURCE
#include <assert.h>
#define nfq_handle_packet mock_handle_packet
#define main prefilter_main
#include "prefilter.c"
#undef main
#undef nfq_handle_packet

static unsigned handled;
int mock_handle_packet(struct nfq_handle *handle, char *buffer, int length) {
    (void)handle; (void)buffer; (void)length;
    handled++; errno = EOPNOTSUPP; return -1;
}

int main(void) {
    unsigned char raw[128] __attribute__((aligned)) = {0};
    struct nlmsghdr *header = (struct nlmsghdr *)raw;
    header->nlmsg_type = NLMSG_ERROR;
    header->nlmsg_len = NLMSG_LENGTH(sizeof(struct nlmsgerr) + sizeof(struct nfgenmsg));
    struct nlmsgerr error = {.error = -ENOENT, .msg = {
        .nlmsg_type = (NFNL_SUBSYS_QUEUE << 8) | NFQNL_MSG_VERDICT,
        .nlmsg_len = NLMSG_LENGTH(sizeof(struct nfgenmsg))}};
    struct nfgenmsg family = {.res_id = htons(100)};
    memcpy(NLMSG_DATA(header), &error, sizeof(error));
    memcpy((char *)NLMSG_DATA(header) + sizeof(error), &family, sizeof(family));
    size_t original = 0;
    assert(handle_datagram(NULL, (char *)raw, header->nlmsg_len, &original, 100) == 0);
    assert(verdict_missing == 1 && handled == 0 && submitted_verdicts == 0);
    for (unsigned test = 0; test < 5; test++) {
        error.error = test == 0 ? -EPERM : test == 1 ? 0 : -ENOENT;
        error.msg.nlmsg_type = (NFNL_SUBSYS_QUEUE << 8) | (test == 2 ? NFQNL_MSG_CONFIG : NFQNL_MSG_VERDICT);
        error.msg.nlmsg_len = test == 4 ? NLMSG_LENGTH(0) : NLMSG_LENGTH(sizeof(family));
        family.res_id = htons(test == 3 ? 101 : 100);
        memcpy(NLMSG_DATA(header), &error, sizeof(error));
        memcpy((char *)NLMSG_DATA(header) + sizeof(error), &family, sizeof(family));
        assert(handle_datagram(NULL, (char *)raw, header->nlmsg_len, &original, 100) < 0);
    }
    assert(handled == 5 && verdict_missing == 1 && submitted_verdicts == 0);
    header->nlmsg_len = NLMSG_LENGTH(sizeof(struct nlmsgerr)) - 1;
    assert(handle_datagram(NULL, (char *)raw, header->nlmsg_len, &original, 100) < 0);
    assert(verdict_missing == 1);
    assert(handle_datagram(NULL, (char *)raw, NLMSG_HDRLEN - 1, &original, 100) < 0 && errno == EPROTO);
    puts("PASS only ENOENT for this queue's individual verdict is nonfatal");
    return 0;
}
