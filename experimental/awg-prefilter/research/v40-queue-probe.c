// SPDX-License-Identifier: MIT
// Isolated loopback NFQUEUE capacity/verdict test; this does not authenticate VPN clients.
// Expected entry counts describe kernel 6.12.117; recheck them on another kernel.
#ifdef NDEBUG
#error "This lab probe requires assertions"
#endif
#define _GNU_SOURCE
#include <net/if.h>
#define main escrow_unused_main
#include "../flow-confirmation/escrow.c"
#undef main

#define TEST_PACKETS 90000U
static struct { uint32_t id;uint16_t queue; } captured[TEST_PACKETS];
static unsigned captured_count,delivered,duplicate_payload;
static unsigned char seen[TEST_PACKETS+1],ids[QUEUES][TEST_PACKETS+1];
static uint64_t input_per_queue[QUEUES];
struct queue_stats { unsigned depth,dropped,user_dropped; };
static void queue_stats(struct queue_stats stats[QUEUES]) {
    memset(stats,0,QUEUES*sizeof(*stats));
    FILE *f=fopen("/proc/net/netfilter/nfnetlink_queue","r");assert(f);
    char line[512];unsigned v[9];
    while(fgets(line,sizeof(line),f)) {
        assert(sscanf(line,"%u %u %u %u %u %u %u %u %u",v,v+1,v+2,v+3,v+4,v+5,v+6,v+7,v+8)==9);
        if(valid_queue((uint16_t)v[0]))stats[v[0]-QUEUE]=(struct queue_stats){v[2],v[5],v[6]};
    }
    assert(!fclose(f));
}
static void collect_queue(void) {
    char buffer[65536] __attribute__((aligned));
    for(;;) {
        ssize_t n=recv(queue_fd,buffer,sizeof(buffer),MSG_DONTWAIT);
        if(n<0){assert(errno==EAGAIN || errno==EWOULDBLOCK);break;}
        int left=(int)n;struct nlmsghdr *h=(void *)buffer;
        while(NLMSG_OK(h,left)) {
            if(missing_verdict(h))verdict_missing++;
            else {
                assert(h->nlmsg_type==((NFNL_SUBSYS_QUEUE<<8)|NFQNL_MSG_PACKET));
                assert(h->nlmsg_len>=NLMSG_LENGTH(sizeof(struct nfgenmsg)));
                struct nfgenmsg *fg=NLMSG_DATA(h);uint16_t q=read16(&fg->res_id);
                assert(valid_queue(q));
                struct nlattr *attrs[NFQA_MAX+1]={0};assert(nfq_nlmsg_parse(h,attrs)>=0 && attrs[NFQA_PACKET_HDR]);
                const struct nfqnl_msg_packet_hdr *ph=(const void *)((const char *)attrs[NFQA_PACKET_HDR]+NLA_HDRLEN);
                uint32_t id=read32(&ph->packet_id);assert(id && id<=TEST_PACKETS && !ids[q-QUEUE][id]);
                ids[q-QUEUE][id]=1;input_per_queue[q-QUEUE]++;assert(captured_count<TEST_PACKETS);
                captured[captured_count].queue=q;captured[captured_count++].id=id;
            }
            h=NLMSG_NEXT(h,left);
        }
        assert(!left);
    }
}
static void collect_udp(int fd) {
    for(;;) {
        uint32_t value;ssize_t n=recv(fd,&value,sizeof(value),MSG_DONTWAIT);
        if(n<0){assert(errno==EAGAIN || errno==EWOULDBLOCK);break;}
        assert(n==(ssize_t)sizeof(value));value=ntohl(value);assert(value && value<=TEST_PACKETS);
        if(seen[value])duplicate_payload++;else{seen[value]=1;delivered++;}
    }
}
int main(int argc,char **argv) {
    assert(argc==3 && !strcmp(argv[1],"--vm-test") && !geteuid());
    int one=!strcmp(argv[2],"one"),two=!strcmp(argv[2],"two"),wrong=!strcmp(argv[2],"wrong"),missing=!strcmp(argv[2],"missing");
    assert(one || two || wrong || missing);
    char hostname[256];assert(!gethostname(hostname,sizeof(hostname)) && !strcmp(hostname,"kit-entry"));
    struct stat self,init;assert(!stat("/proc/self/ns/net",&self) && !stat("/proc/1/ns/net",&init) && self.st_ino!=init.st_ino);
    struct if_nameindex *interfaces=if_nameindex();assert(interfaces);unsigned count=0;
    for(struct if_nameindex *v=interfaces;v->if_index;v++){assert(!strcmp(v->if_name,"lo"));count++;}
    if_freenameindex(interfaces);assert(count==1);
    struct nfq_handle *handle=nfq_open();assert(handle && !nfq_bind_pf(handle,AF_INET));
    unsigned queues=(one || missing)?1:QUEUES;struct nfq_q_handle *q[QUEUES];
    for(unsigned i=0;i<queues;i++) {
        q[i]=nfq_create_queue(handle,(uint16_t)(QUEUE+i),NULL,NULL);
        assert(q[i] && !nfq_set_mode(q[i],NFQNL_COPY_META,0) && !nfq_set_queue_maxlen(q[i],CAPACITY));
    }
    queue_fd=nfq_fd(handle);int netbuf=16*1024*1024,sendbuf=128*1024*1024,recvbuf=4*1024*1024;
    assert(!setsockopt(queue_fd,SOL_SOCKET,SO_RCVBUFFORCE,&netbuf,sizeof(netbuf)));
    int rx=socket(AF_INET,SOCK_DGRAM|SOCK_NONBLOCK,0),tx=socket(AF_INET,SOCK_DGRAM|SOCK_NONBLOCK,0);assert(rx>=0 && tx>=0);
    assert(!setsockopt(rx,SOL_SOCKET,SO_RCVBUFFORCE,&recvbuf,sizeof(recvbuf)));
    assert(!setsockopt(tx,SOL_SOCKET,SO_SNDBUFFORCE,&sendbuf,sizeof(sendbuf)));
    struct sockaddr_in address={.sin_family=AF_INET,.sin_port=htons(5353),.sin_addr.s_addr=htonl(INADDR_LOOPBACK)};
    assert(!bind(rx,(void *)&address,sizeof(address)));
    unsigned attempted=(wrong || missing)?512:TEST_PACKETS,sent=0,send_errors=0;
    uint64_t start=clock_ns();
    for(unsigned i=0;i<attempted;i++) {
        uint64_t next=start+(uint64_t)i*100000;struct timespec at={.tv_sec=(time_t)(next/TTL_NS),.tv_nsec=(long)(next%TTL_NS)};
        int rc;do{rc=clock_nanosleep(CLOCK_MONOTONIC,TIMER_ABSTIME,&at,NULL);}while(rc==EINTR);assert(!rc);
        uint32_t payload=htonl(i+1);ssize_t n=sendto(tx,&payload,sizeof(payload),0,(void *)&address,sizeof(address));
        if(n==(ssize_t)sizeof(payload))sent++;else{assert(n==-1);send_errors++;}
        collect_queue();
    }
    uint64_t until=clock_ns()+TTL_NS/4;
    while(clock_ns()<until){collect_queue();usleep(1000);}
    struct queue_stats before[QUEUES],after[QUEUES];queue_stats(before);
    unsigned overlap=0;for(unsigned i=1;i<=TEST_PACKETS;i++)overlap+=ids[0][i] && ids[1][i];
    assert(captured_count==before[0].depth+before[1].depth && !before[0].user_dropped && !before[1].user_dropped);
    for(unsigned i=0;i<captured_count;i++) {
        verdict(wrong?QUEUE:captured[i].queue,captured[i].id,0,1);
        if(i%64==63){assert(!flush());collect_udp(rx);collect_queue();}
    }
    assert(!flush());until=clock_ns()+TTL_NS/2;
    while(clock_ns()<until){collect_udp(rx);collect_queue();usleep(1000);}
    queue_stats(after);assert(!duplicate_payload);
    printf("{\"mode\":\"%s\",\"attempted\":%u,\"send_succeeded\":%u,\"send_errors\":%u,\"NFQUEUE_received\":%u,\"queue_received\":[%"PRIu64",%"PRIu64"],\"queue_drops\":[%u,%u],\"queue_user_drops\":[%u,%u],\"queue_depth_before\":[%u,%u],\"overlapping_packet_IDs\":%u,\"UDP_unique\":%u,\"UDP_duplicates\":%u,\"queue_depth_after\":[%u,%u],\"verdict_missing\":%"PRIu64",\"negative_control\":%s}\n",argv[2],attempted,sent,send_errors,captured_count,input_per_queue[0],input_per_queue[1],before[0].dropped,before[1].dropped,before[0].user_dropped,before[1].user_dropped,before[0].depth,before[1].depth,overlap,delivered,duplicate_payload,after[0].depth,after[1].depth,verdict_missing,(wrong || missing)?"true":"false");fflush(stdout);
    int ok=one?(captured_count==65536 && before[0].dropped==attempted-captured_count && delivered==captured_count):
        two?(captured_count==attempted && delivered==attempted && !before[0].dropped && !before[1].dropped && overlap==attempted/2):
        wrong?(delivered==attempted/2 && after[1].depth==attempted/2 && verdict_missing==attempted/2):
        (captured_count==attempted/2 && delivered==attempted/2);
    if(!wrong)ok=ok && !after[0].depth && !after[1].depth;
    for(unsigned i=0;i<queues;i++)nfq_destroy_queue(q[i]);
    nfq_close(handle);close(rx);close(tx);return ok?0:1;
}
