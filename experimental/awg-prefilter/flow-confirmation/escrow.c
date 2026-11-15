// SPDX-License-Identifier: MIT
// Disposable IPv4 lab only: retain excess skbs until the existing exit proof.
#define _GNU_SOURCE
#include <arpa/inet.h>
#include <assert.h>
#include <errno.h>
#include <inttypes.h>
#include <linux/netfilter.h>
#include <linux/netfilter/nf_conntrack_common.h>
#include <linux/netfilter/nfnetlink_conntrack.h>
#include <linux/netfilter/nfnetlink_queue.h>
#include <libnetfilter_queue/libnetfilter_queue.h>
#include <poll.h>
#include <signal.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/un.h>
#include <time.h>
#include <unistd.h>

#define CAPACITY 32768U
#define FLOW_LIMIT 128U
#define PER_FLOW 4096U
#define BYTE_LIMIT (8U * 1024U * 1024U)
#define TTL_NS UINT64_C(1000000000)
#define RELEASE_MARK UINT32_C(0x08000000)
#define BATCH 16U
#define QUEUE 101

struct key { uint32_t ip, ct; uint16_t port; };
struct flow { struct key key; unsigned count; };
struct grant { struct key key; uint64_t until; };
struct packet { uint64_t until; uint32_t id, mark; uint16_t length, flow; };
static struct flow flows[FLOW_LIMIT];
static struct grant grants[FLOW_LIMIT];
static struct packet packets[CAPACITY];
static uint64_t head, tail;
static unsigned grant_count, held, held_bytes;
static uint64_t received, released, expired, bounded, invalid, control_bad, control_ok;
static uint64_t high_packets, high_bytes, netlink_enobufs, send_calls;
static volatile sig_atomic_t stopping, reporting;
static int queue_fd, testing;
static unsigned verdict_count;
static char verdict_buffers[BATCH][256] __attribute__((aligned));
static struct iovec verdict_iov[BATCH];

static void fatal(const char *why) { perror(why); exit(1); }
static uint64_t clock_ns(void) {
    struct timespec ts;
    if (clock_gettime(CLOCK_MONOTONIC, &ts)) fatal("clock_gettime");
    return (uint64_t)ts.tv_sec * UINT64_C(1000000000) + (uint64_t)ts.tv_nsec;
}
static int equal(struct key a, struct key b) {
    return a.ip == b.ip && a.ct == b.ct && a.port == b.port;
}
static uint16_t read16(const void *p) { uint16_t v; memcpy(&v,p,2); return ntohs(v); }
static uint32_t read32(const void *p) { uint32_t v; memcpy(&v,p,4); return ntohl(v); }
static uint64_t read64(const void *p) {
    return ((uint64_t)read32(p) << 32) | read32((const char *)p + 4);
}
static int flush(void) {
    if (!verdict_count) return 0;
    struct sockaddr_nl kernel = { .nl_family = AF_NETLINK };
    struct msghdr msg = { .msg_name=&kernel, .msg_namelen=sizeof(kernel),
                         .msg_iov=verdict_iov, .msg_iovlen=verdict_count };
    size_t wanted=0;
    for (unsigned i=0;i<verdict_count;i++) wanted+=verdict_iov[i].iov_len;
    ssize_t n;
    do { send_calls++; n=sendmsg(queue_fd,&msg,0); } while (n<0 && errno==EINTR);
    if (n<0 || (size_t)n!=wanted) return -1;
    verdict_count=0; return 0;
}
static void verdict(uint32_t id, uint32_t mark, int accept) {
    if (testing) return;
    struct nlmsghdr *h=nfq_nlmsg_put(verdict_buffers[verdict_count],NFQNL_MSG_VERDICT,QUEUE);
    h->nlmsg_flags=NLM_F_REQUEST;
    nfq_nlmsg_verdict_put(h,(int)id,accept?NF_ACCEPT:NF_DROP);
    nfq_nlmsg_verdict_put_mark(h,mark | (accept?RELEASE_MARK:0));
    verdict_iov[verdict_count++]=(struct iovec){.iov_base=h,.iov_len=h->nlmsg_len};
    if (verdict_count==BATCH && flush()) fatal("send verdicts");
}
static void remove_packet(struct packet *p, int accept) {
    assert(p->length && flows[p->flow].count);
    verdict(p->id,p->mark,accept);
    flows[p->flow].count--; held--; held_bytes-=p->length; p->length=0;
    if (accept) released++; else expired++;
}
static void expire(uint64_t now) {
    while (head<tail) {
        struct packet *p=&packets[head%CAPACITY];
        if (p->length && p->until>now) break;
        if (p->length) remove_packet(p,0);
        head++;
    }
}
static int authorized(struct key key, uint64_t now) {
    for (unsigned i=0;i<grant_count;i++)
        if (grants[i].until>now && equal(grants[i].key,key)) return 1;
    return 0;
}
static void hold(struct key key, uint32_t id, uint32_t mark, unsigned length, uint64_t now) {
    received++; expire(now);
    if (authorized(key,now)) { verdict(id,mark,1); released++; return; }
    unsigned f, free_flow=FLOW_LIMIT;
    for (f=0;f<FLOW_LIMIT;f++) {
        if (flows[f].count && equal(flows[f].key,key)) break;
        if (!flows[f].count) free_flow=f;
    }
    if (f==FLOW_LIMIT) f=free_flow;
    if (f==FLOW_LIMIT || tail-head==CAPACITY || held_bytes+length>BYTE_LIMIT || flows[f].count>=PER_FLOW) {
        bounded++; verdict(id,mark,0); return;
    }
    if (!flows[f].count) flows[f].key=key;
    struct packet *p=&packets[tail++%CAPACITY];
    *p=(struct packet){.until=now+TTL_NS,.id=id,.mark=mark,.length=(uint16_t)length,.flow=(uint16_t)f};
    flows[f].count++; held++; held_bytes+=length;
    if (held>high_packets) high_packets=held;
    if (held_bytes>high_bytes) high_bytes=held_bytes;
}
static int control(const unsigned char *data, size_t size, int root, uint64_t now) {
    if (!root || size<6 || memcmp(data,"CWE1",4)) return 0;
    unsigned count=read16(data+4);
    if (count>FLOW_LIMIT || size!=6+18*count) return 0;
    struct grant next[FLOW_LIMIT];
    for (unsigned i=0;i<count;i++) {
        const unsigned char *r=data+6+18*i;
        memcpy(&next[i].key.ip,r,4);
        next[i].key.port=read16(r+4); next[i].key.ct=read32(r+6); next[i].until=read64(r+10);
        if (!next[i].key.port || !next[i].key.ct || next[i].until<=now || next[i].until-now>11*TTL_NS) return 0;
        for (unsigned j=0;j<i;j++) if (equal(next[i].key,next[j].key)) return 0;
    }
    memcpy(grants,next,count*sizeof(*next)); grant_count=count;
    expire(now);
    for (uint64_t i=head;i<tail;i++) {
        struct packet *p=&packets[i%CAPACITY];
        if (p->length && authorized(flows[p->flow].key,now)) remove_packet(p,1);
    }
    expire(now); return 1;
}
static void report(void) {
    printf("{\"received\":%"PRIu64",\"released\":%"PRIu64",\"expired\":%"PRIu64
           ",\"bounded\":%"PRIu64",\"invalid\":%"PRIu64",\"control_bad\":%"PRIu64
           ",\"control_ok\":%"PRIu64",\"held\":%u,\"held_bytes\":%u,\"high_packets\":%"PRIu64
           ",\"high_bytes\":%"PRIu64",\"netlink_enobufs\":%"PRIu64",\"send_calls\":%"PRIu64"}\n",
           received,released,expired,bounded,invalid,control_bad,control_ok,held,held_bytes,high_packets,high_bytes,netlink_enobufs,send_calls);
    fflush(stdout);
}
static void signal_handler(int sig) { if (sig==SIGUSR1) reporting=1; else stopping=1; }

static int conntrack(struct nlattr *attr, uint32_t *id) {
    if (!attr || attr->nla_len<NLA_HDRLEN) return 0;
    size_t left=attr->nla_len-NLA_HDRLEN;
    const unsigned char *p=(unsigned char *)attr+NLA_HDRLEN;
    uint32_t status=0; *id=0;
    while (left>=NLA_HDRLEN) {
        const struct nlattr *a=(const struct nlattr *)p;
        if (a->nla_len<NLA_HDRLEN || a->nla_len>left) return 0;
        unsigned kind=a->nla_type & NLA_TYPE_MASK;
        if (kind==CTA_ID || kind==CTA_STATUS) {
            if (a->nla_len!=NLA_HDRLEN+4) return 0;
            uint32_t v=read32(p+NLA_HDRLEN);
            if (kind==CTA_ID) *id=v; else status=v;
        }
        size_t step=NLA_ALIGN(a->nla_len);
        if (step>left) return 0;
        p+=step; left-=step;
    }
    return !left && *id && (status & IPS_CONFIRMED);
}
static int parse_packet(struct nlmsghdr *h) {
    struct nlattr *a[NFQA_MAX+1]={0};
    if (nfq_nlmsg_parse(h,a)<0 || !a[NFQA_PACKET_HDR] ||
        a[NFQA_PACKET_HDR]->nla_len!=NLA_HDRLEN+sizeof(struct nfqnl_msg_packet_hdr)) return -1;
    struct nfqnl_msg_packet_hdr ph;
    memcpy(&ph,(char *)a[NFQA_PACKET_HDR]+NLA_HDRLEN,sizeof(ph));
    uint32_t id=ntohl(ph.packet_id), mark=0;
    if (a[NFQA_MARK]) {
        if (a[NFQA_MARK]->nla_len!=NLA_HDRLEN+4) return -1;
        mark=read32((char *)a[NFQA_MARK]+NLA_HDRLEN);
    }
    struct key key={0};
    size_t size=a[NFQA_PAYLOAD]?a[NFQA_PAYLOAD]->nla_len-NLA_HDRLEN:0;
    const unsigned char *ip=a[NFQA_PAYLOAD]?(unsigned char *)a[NFQA_PAYLOAD]+NLA_HDRLEN:NULL;
    if (ph.hook!=NF_INET_PRE_ROUTING || !conntrack(a[NFQA_CT],&key.ct) || size<28 ||
        (ip[0]>>4)!=4 || (ip[0]&15)<5 || ip[9]!=IPPROTO_UDP || (read16(ip+6)&0x3fff)) goto reject;
    unsigned ihl=(ip[0]&15)*4U, length=read16(ip+2);
    if (size<ihl+8 || length<ihl+8 || length>1536 || read16(ip+ihl+4)!=length-ihl || read16(ip+ihl+2)!=32497) goto reject;
    if (a[NFQA_CAP_LEN] && (a[NFQA_CAP_LEN]->nla_len!=NLA_HDRLEN+4 || read32((char *)a[NFQA_CAP_LEN]+NLA_HDRLEN)!=length)) goto reject;
    memcpy(&key.ip,ip+12,4); key.port=read16(ip+ihl);
    if (!key.port || (mark & RELEASE_MARK)) goto reject;
    hold(key,id,mark,length,clock_ns()); return 0;
reject:
    invalid++; verdict(id,mark,0); return 0;
}
static void selftest(void) {
    testing=1;
    unsigned char attrs[20] __attribute__((aligned))={0};
    struct nlattr *outer=(struct nlattr *)attrs,*identity=(struct nlattr *)(attrs+4),*state=(struct nlattr *)(attrs+12);
    outer->nla_len=sizeof(attrs);identity->nla_len=8;identity->nla_type=CTA_ID;
    state->nla_len=8;state->nla_type=CTA_STATUS;
    uint32_t value=htonl(789),parsed=0;memcpy(attrs+8,&value,4);
    assert(!conntrack(outer,&parsed));
    value=htonl(IPS_CONFIRMED);memcpy(attrs+16,&value,4);
    assert(conntrack(outer,&parsed) && parsed==789);
    identity->nla_len=7;assert(!conntrack(outer,&parsed));identity->nla_len=8;
    value=0;memcpy(attrs+8,&value,4);assert(!conntrack(outer,&parsed));
    struct key k={.ip=123,.port=456,.ct=789}, other=k; other.ct++;
    hold(k,0,0,128,1); hold(other,1,0,128,1);
    unsigned char message[24]={ 'C','W','E','1',0,1 };
    memcpy(message+6,&k.ip,4);
    uint16_t p=htons(k.port); uint32_t c=htonl(k.ct), n=htonl(1000);
    memcpy(message+10,&p,2); memcpy(message+12,&c,4); memcpy(message+20,&n,4);
    assert(!control(message,sizeof(message),0,2));
    assert(!control(message,sizeof(message)-1,1,2));
    assert(control(message,sizeof(message),1,2) && released==1 && held==1);
    hold(k,2,0,128,3); assert(released==2 && held==1);
    assert(control((unsigned char *)"CWE1\0\0",6,1,4));
    hold(k,3,0,128,5); assert(held==2);
    expire(TTL_NS+6); assert(!held && expired==2 && head==tail);
    for (unsigned i=0;i<PER_FLOW+1;i++) hold(k,i,0,1536,2*TTL_NS);
    assert(held==PER_FLOW && bounded==1);
    expire(3*TTL_NS); assert(!held && !held_bytes);
    for (unsigned i=0;i<FLOW_LIMIT;i++) { k.ct=i+1; hold(k,i,0,128,4*TTL_NS); }
    k.ct=FLOW_LIMIT+1; hold(k,99,0,128,4*TTL_NS); assert(held==FLOW_LIMIT && bounded==2);
    expire(5*TTL_NS); assert(!held);
    for (unsigned i=0;i<CAPACITY+1;i++) { k.ct=i%8+1; hold(k,i,0,128,6*TTL_NS); }
    assert(held==CAPACITY && bounded==3);
    expire(7*TTL_NS); assert(!held && head==tail);
    for (unsigned i=0;i<6000;i++) { k.ct=i%8+1; hold(k,i,0,1536,8*TTL_NS); }
    assert(held_bytes<=BYTE_LIMIT && bounded>3);
    expire(9*TTL_NS); assert(!held && !held_bytes);
    message[4]=0; message[5]=129; assert(!control(message,sizeof(message),1,2));
    puts("PASS escrow identity, revocation, expiry, packet/flow/byte bounds and root-only snapshots");
}
int main(int argc, char **argv) {
    if (argc==2 && !strcmp(argv[1],"--self-test")) { selftest(); return 0; }
    if (argc!=2 || strcmp(argv[1],"--vm-test") || geteuid()) {
        fputs("Usage: escrow --self-test | --vm-test (root, kit-entry only)\n",stderr); return 1;
    }
    char hostname[256];
    if (gethostname(hostname,sizeof(hostname)) || strcmp(hostname,"kit-entry")) return 1;
    const char *directory="/run/coldwire-escrow", *path="/run/coldwire-escrow/grants.sock";
    struct stat st;
    if (lstat(directory,&st) || !S_ISDIR(st.st_mode) || st.st_uid || (st.st_mode&0777)!=0700) fatal("private directory");
    int control_fd=socket(AF_UNIX,SOCK_DGRAM|SOCK_NONBLOCK|SOCK_CLOEXEC,0), one=1;
    struct sockaddr_un addr={.sun_family=AF_UNIX};
    strcpy(addr.sun_path,path);
    if (control_fd<0 || setsockopt(control_fd,SOL_SOCKET,SO_PASSCRED,&one,sizeof(one)) ||
        bind(control_fd,(struct sockaddr *)&addr,sizeof(addr)) || chmod(path,0600)) fatal("control socket");
    struct sigaction sa={.sa_handler=signal_handler}; sigemptyset(&sa.sa_mask);
    if (sigaction(SIGTERM,&sa,NULL) || sigaction(SIGINT,&sa,NULL) || sigaction(SIGUSR1,&sa,NULL)) fatal("signals");
    struct nfq_handle *handle=nfq_open();
    if (!handle || nfq_bind_pf(handle,AF_INET)) fatal("NFQUEUE open");
    // Raw packet parsing retains the original skb; no copied payload is reinjected.
    struct nfq_q_handle *q=nfq_create_queue(handle,QUEUE,NULL,NULL);
    if (!q || nfq_set_mode(q,NFQNL_COPY_PACKET,128) || nfq_set_queue_maxlen(q,CAPACITY) ||
        nfq_set_queue_flags(q,NFQA_CFG_F_CONNTRACK,NFQA_CFG_F_CONNTRACK)) fatal("NFQUEUE config");
    queue_fd=nfq_fd(handle); int buffer_size=4*1024*1024;
    if (setsockopt(queue_fd,SOL_SOCKET,SO_RCVBUFFORCE,&buffer_size,sizeof(buffer_size))) fatal("netlink buffer");
    char buffers[BATCH][8192] __attribute__((aligned));
    struct iovec iov[BATCH]; struct mmsghdr incoming[BATCH]={0};
    for (unsigned i=0;i<BATCH;i++) {
        iov[i]=(struct iovec){.iov_base=buffers[i],.iov_len=sizeof(buffers[i])};
        incoming[i].msg_hdr.msg_iov=&iov[i]; incoming[i].msg_hdr.msg_iovlen=1;
    }
    puts("ready queue=101 copy=128 max=32768 ttl_ms=1000 byte_limit=8388608"); fflush(stdout);
    int status=0;
    while (!stopping) {
        expire(clock_ns()); if (flush()) { status=1; break; }
        if (reporting) { report(); reporting=0; }
        struct pollfd fds[2]={{.fd=control_fd,.events=POLLIN},{.fd=queue_fd,.events=POLLIN}};
        if (poll(fds,2,10)<0) { if (errno==EINTR) continue; status=1; break; }
        if ((fds[0].revents|fds[1].revents)&(POLLHUP|POLLNVAL) || (fds[0].revents&POLLERR)) {
            fputs("poll: control/queue closed\n",stderr); status=1; break;
        }
        if (fds[0].revents&POLLIN) {
            unsigned char data[6+18*FLOW_LIMIT]; char ancillary[CMSG_SPACE(sizeof(struct ucred))] __attribute__((aligned));
            struct iovec v={.iov_base=data,.iov_len=sizeof(data)};
            struct msghdr msg={.msg_iov=&v,.msg_iovlen=1,.msg_control=ancillary,.msg_controllen=sizeof(ancillary)};
            ssize_t n=recvmsg(control_fd,&msg,MSG_DONTWAIT); int root=0;
            if (n>=0 && !(msg.msg_flags&(MSG_TRUNC|MSG_CTRUNC))) {
                for (struct cmsghdr *c=CMSG_FIRSTHDR(&msg);c;c=CMSG_NXTHDR(&msg,c))
                    if (c->cmsg_level==SOL_SOCKET && c->cmsg_type==SCM_CREDENTIALS && c->cmsg_len==CMSG_LEN(sizeof(struct ucred))) {
                        struct ucred cred; memcpy(&cred,CMSG_DATA(c),sizeof(cred)); root=cred.uid==0;
                    }
                if (control(data,(size_t)n,root,clock_ns())) control_ok++; else control_bad++;
            } else if (n>=0) control_bad++;
        }
        if (fds[1].revents&(POLLIN|POLLERR)) {
            int n=recvmmsg(queue_fd,incoming,BATCH,MSG_DONTWAIT,NULL);
            if (n<0) {
                if (errno==ENOBUFS) { netlink_enobufs++; continue; }
                if (errno==EINTR || errno==EAGAIN) continue;
                status=1; break;
            }
            for (int i=0;i<n;i++) {
                if (incoming[i].msg_hdr.msg_flags&(MSG_TRUNC|MSG_CTRUNC)) { status=1; break; }
                int left=(int)incoming[i].msg_len;
                struct nlmsghdr *h=(struct nlmsghdr *)buffers[i];
                while (NLMSG_OK(h,left)) {
                    if (h->nlmsg_type!=((NFNL_SUBSYS_QUEUE<<8)|NFQNL_MSG_PACKET) || parse_packet(h)) {
                        fprintf(stderr,"netlink type=%u bytes=%u errno=%d",h->nlmsg_type,h->nlmsg_len,errno);
                        if (h->nlmsg_type==NLMSG_ERROR && h->nlmsg_len>=NLMSG_LENGTH(sizeof(struct nlmsgerr))) {
                            struct nlmsgerr e;memcpy(&e,NLMSG_DATA(h),sizeof(e));fprintf(stderr," kernel_error=%d",e.error);
                        }
                        fputc('\n',stderr);status=1;break;
                    }
                    if (h->nlmsg_len==(unsigned)left) { left=0; break; }
                    h=NLMSG_NEXT(h,left);
                }
                if (left) status=1;
                if (status) break;
            }
            if (status) break;
        }
    }
    expire(UINT64_MAX); if (flush()) status=1; report();
    nfq_destroy_queue(q); nfq_close(handle); close(control_fd); unlink(path);
    return status;
}
