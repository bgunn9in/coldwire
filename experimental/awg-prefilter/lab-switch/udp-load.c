#define _GNU_SOURCE
#include <arpa/inet.h>
#include <assert.h>
#include <errno.h>
#include <inttypes.h>
#include <poll.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <time.h>
#include <unistd.h>

enum { PPS=6000, SECONDS=60, TOTAL=PPS*SECONDS, BATCH=32, PORT=5201 };
static uint64_t ns(clockid_t id) { struct timespec t;assert(!clock_gettime(id,&t));return (uint64_t)t.tv_sec*1000000000+t.tv_nsec; }
static void packet(unsigned char *p,size_t size,uint32_t n) { memset(p,0,size);memcpy(p,"CWUDP36!",8);n=htonl(n);memcpy(p+8,&n,4); }
static uint32_t sequence(const unsigned char *p,size_t size,size_t expected,unsigned total) {
    uint32_t n;if(size!=expected || memcmp(p,"CWUDP36!",8))return 0;
    memcpy(&n,p+8,4);n=ntohl(n);return n && n<=total?n:0;
}
static struct sockaddr_in address(const char *text) {
    assert(!strcmp(text,"10.8.1.1") || !strcmp(text,"10.8.1.2") || !strcmp(text,"10.8.1.3"));
    struct sockaddr_in a={.sin_family=AF_INET,.sin_port=htons(PORT)};assert(inet_pton(AF_INET,text,&a.sin_addr)==1);return a;
}
static void missing_by_second(const unsigned char *seen, unsigned *counts, unsigned pps, unsigned total) {
    for (unsigned i = 0; i < total; i++) {
        if (!seen[i + 1]) counts[i / pps]++;
    }
}
static unsigned bounded_number(const char *text, unsigned maximum) {
    assert(*text && strspn(text,"0123456789")==strlen(text));
    unsigned long value=strtoul(text,NULL,10);
    assert(value && value<=maximum);
    return (unsigned)value;
}
int main(int argc,char **argv) {
    if(argc==2 && !strcmp(argv[1],"--self-test")) {
        unsigned char p[1200];packet(p,sizeof(p),1);assert(sequence(p,sizeof(p),1200,TOTAL)==1);
        packet(p,sizeof(p),TOTAL);assert(sequence(p,sizeof(p),1200,TOTAL)==TOTAL);
        packet(p,sizeof(p),TOTAL+1);assert(!sequence(p,sizeof(p),1200,TOTAL));
        packet(p,sizeof(p),1);p[0]^=1;assert(!sequence(p,sizeof(p),1200,TOTAL));
        assert(!sequence(p,12,1200,TOTAL));
        unsigned char *seen = malloc(TOTAL + 1);
        assert(seen);
        memset(seen, 1, TOTAL + 1);
        seen[1] = seen[PPS] = seen[PPS + 1] = seen[TOTAL] = 0;
        unsigned missing[SECONDS] = {0};
        missing_by_second(seen, missing, PPS, TOTAL);
        assert(missing[0] == 2 && missing[1] == 1 && missing[SECONDS - 1] == 1);
        for (unsigned i = 2; i < SECONDS - 1; i++) assert(!missing[i]);
        unsigned short_run[3]={0};
        missing_by_second((unsigned char[]){0,1,0,0,1,0,0},short_run,2,6);
        assert(short_run[0]==1 && short_run[1]==1 && short_run[2]==2);
        assert(bounded_number("900",900)==900);
        free(seen);
        puts("PASS bounded UDP sequence validation and missing-packet bins");
        return 0;
    }
    char host[64];assert(!gethostname(host,sizeof(host)) && !geteuid());
    assert(!strcmp(host,"kit-exit") || !strcmp(host,"kit-client"));
    assert(argc>=4);
    int sending=!strcmp(argv[1],"send");assert(sending || !strcmp(argv[1],"recv"));
    int mandatory=sending?5:4;
    assert(argc==mandatory || argc==mandatory+2);
    unsigned pps=argc==mandatory?PPS:bounded_number(argv[mandatory],PPS);
    unsigned seconds=argc==mandatory?SECONDS:bounded_number(argv[mandatory+1],900);
    unsigned total=pps*seconds;
    size_t size=bounded_number(argv[mandatory-1],1200);assert(size==128 || size==1200);
    struct sockaddr_in local=address(argv[2]);assert((!strcmp(host,"kit-exit"))==(!strcmp(argv[2],"10.8.1.1")));
    int fd=socket(AF_INET,SOCK_DGRAM|SOCK_CLOEXEC,0);assert(fd>=0);
    int bytes=4*1024*1024;assert(!setsockopt(fd,SOL_SOCKET,sending?SO_SNDBUF:SO_RCVBUFFORCE,&bytes,sizeof(bytes)));
    int actual=0;socklen_t actual_size=sizeof(actual);assert(!getsockopt(fd,SOL_SOCKET,sending?SO_SNDBUF:SO_RCVBUF,&actual,&actual_size));assert(sending || actual>=bytes);
    if(sending)local.sin_port=0;
    assert(!bind(fd,(void *)&local,sizeof(local)));
    uint64_t start=ns(CLOCK_MONOTONIC),wall=ns(CLOCK_REALTIME);
    if(sending) {
        struct sockaddr_in target=address(argv[3]);assert(target.sin_addr.s_addr!=local.sin_addr.s_addr);
        unsigned char data[BATCH][1200];struct iovec iov[BATCH]={0};struct mmsghdr msg[BATCH]={0};
        for(unsigned i=0;i<BATCH;i++){iov[i].iov_base=data[i];iov[i].iov_len=size;msg[i].msg_hdr.msg_iov=&iov[i];msg[i].msg_hdr.msg_iovlen=1;msg[i].msg_hdr.msg_name=&target;msg[i].msg_hdr.msg_namelen=sizeof(target);}
        struct timeval timeout={.tv_sec=1};assert(!setsockopt(fd,SOL_SOCKET,SO_SNDTIMEO,&timeout,sizeof(timeout)));
        unsigned sent=0;
        while(sent<total) {
            uint64_t at=start+(uint64_t)sent*1000000000/pps;struct timespec t={(time_t)(at/1000000000),(long)(at%1000000000)};
            int e;do{e=clock_nanosleep(CLOCK_MONOTONIC,TIMER_ABSTIME,&t,NULL);}while(e==EINTR);assert(!e);
            unsigned count=total-sent<BATCH?total-sent:BATCH;
            for(unsigned i=0;i<count;i++){packet(data[i],size,sent+i+1);msg[i].msg_len=0;}
            unsigned done=0;
            while(done<count){int n=sendmmsg(fd,msg+done,count-done,0);if(n<0 && errno==EINTR)continue;assert(n>0);done+=(unsigned)n;}
            sent+=count;
        }
        uint64_t at=start+(uint64_t)seconds*1000000000;struct timespec t={(time_t)(at/1000000000),(long)(at%1000000000)};
        while(clock_nanosleep(CLOCK_MONOTONIC,TIMER_ABSTIME,&t,NULL)==EINTR){}
        uint64_t end=ns(CLOCK_MONOTONIC);
        printf("{\"tool\":\"coldwire-lab-udp36\",\"sent\":%u,\"payload\":%zu,\"start_monotonic_ns\":%"PRIu64",\"end_monotonic_ns\":%"PRIu64",\"start_wall_ns\":%"PRIu64",\"end_wall_ns\":%"PRIu64",\"seconds\":%.9f,\"batch\":%u,\"socket_buffer_bytes\":%d}\n",sent,size,start,end,wall,ns(CLOCK_REALTIME),(double)(end-start)/1e9,BATCH,actual);
    } else {
        unsigned char *seen=calloc(total+1,1),data[1536];assert(seen);unsigned unique=0,duplicate=0,invalid=0;
        while(ns(CLOCK_MONOTONIC)-start<(uint64_t)(seconds+7)*1000000000) {
            struct pollfd p={.fd=fd,.events=POLLIN};int ready=poll(&p,1,50);if(ready<0 && errno==EINTR)continue;assert(ready>=0);if(!ready)continue;
            for(;;){ssize_t n=recv(fd,data,sizeof(data),MSG_DONTWAIT);if(n<0 && (errno==EAGAIN || errno==EWOULDBLOCK))break;if(n<0 && errno==EINTR)continue;assert(n>=0);uint32_t v=sequence(data,(size_t)n,size,total);if(!v)invalid++;else if(seen[v])duplicate++;else{seen[v]=1;unique++;}}
        }
        uint64_t end_wall = ns(CLOCK_REALTIME);
        unsigned *missing=calloc(seconds,sizeof(*missing));assert(missing);
        missing_by_second(seen, missing, pps, total);
        free(seen);
        printf("{\"tool\":\"coldwire-lab-udp36\",\"unique\":%u,\"duplicates\":%u,\"invalid\":%u,\"payload\":%zu,\"socket_buffer_bytes\":%d,\"start_wall_ns\":%"PRIu64",\"end_wall_ns\":%"PRIu64",\"missing_by_scheduled_second\":[",unique,duplicate,invalid,size,actual,wall,end_wall);
        for (unsigned i = 0; i < seconds; i++) printf("%s%u", i ? "," : "", missing[i]);
        free(missing);
        puts("]}");
    }
    close(fd);return 0;
}
