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
static uint32_t sequence(const unsigned char *p,size_t size,size_t expected) {
    uint32_t n;if(size!=expected || memcmp(p,"CWUDP36!",8))return 0;
    memcpy(&n,p+8,4);n=ntohl(n);return n && n<=TOTAL?n:0;
}
static struct sockaddr_in address(const char *text) {
    assert(!strcmp(text,"10.8.1.1") || !strcmp(text,"10.8.1.2"));
    struct sockaddr_in a={.sin_family=AF_INET,.sin_port=htons(PORT)};assert(inet_pton(AF_INET,text,&a.sin_addr)==1);return a;
}
int main(int argc,char **argv) {
    if(argc==2 && !strcmp(argv[1],"--self-test")) {
        unsigned char p[1200];packet(p,sizeof(p),1);assert(sequence(p,sizeof(p),1200)==1);
        packet(p,sizeof(p),TOTAL);assert(sequence(p,sizeof(p),1200)==TOTAL);
        packet(p,sizeof(p),TOTAL+1);assert(!sequence(p,sizeof(p),1200));
        packet(p,sizeof(p),1);p[0]^=1;assert(!sequence(p,sizeof(p),1200));
        assert(!sequence(p,12,1200));puts("PASS bounded UDP sequence encoding and validation");return 0;
    }
    char host[64];assert(!gethostname(host,sizeof(host)) && !geteuid());
    assert(!strcmp(host,"kit-exit") || !strcmp(host,"kit-client"));
    assert(argc==4 || argc==5);int sending=!strcmp(argv[1],"send");assert(sending || !strcmp(argv[1],"recv"));assert(argc==(sending?5:4));
    size_t size=strtoul(argv[sending?4:3],NULL,10);assert(size==128 || size==1200);
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
        while(sent<TOTAL) {
            uint64_t at=start+(uint64_t)sent*1000000000/PPS;struct timespec t={(time_t)(at/1000000000),(long)(at%1000000000)};
            int e;do{e=clock_nanosleep(CLOCK_MONOTONIC,TIMER_ABSTIME,&t,NULL);}while(e==EINTR);assert(!e);
            unsigned count=TOTAL-sent<BATCH?TOTAL-sent:BATCH;
            for(unsigned i=0;i<count;i++){packet(data[i],size,sent+i+1);msg[i].msg_len=0;}
            unsigned done=0;
            while(done<count){int n=sendmmsg(fd,msg+done,count-done,0);if(n<0 && errno==EINTR)continue;assert(n>0);done+=(unsigned)n;}
            sent+=count;
        }
        uint64_t at=start+(uint64_t)SECONDS*1000000000;struct timespec t={(time_t)(at/1000000000),(long)(at%1000000000)};
        while(clock_nanosleep(CLOCK_MONOTONIC,TIMER_ABSTIME,&t,NULL)==EINTR){}
        uint64_t end=ns(CLOCK_MONOTONIC);
        printf("{\"tool\":\"coldwire-lab-udp36\",\"sent\":%u,\"payload\":%zu,\"start_monotonic_ns\":%"PRIu64",\"end_monotonic_ns\":%"PRIu64",\"start_wall_ns\":%"PRIu64",\"end_wall_ns\":%"PRIu64",\"seconds\":%.9f,\"batch\":%u,\"socket_buffer_bytes\":%d}\n",sent,size,start,end,wall,ns(CLOCK_REALTIME),(double)(end-start)/1e9,BATCH,actual);
    } else {
        unsigned char *seen=calloc(TOTAL+1,1),data[1536];assert(seen);unsigned unique=0,duplicate=0,invalid=0;
        while(ns(CLOCK_MONOTONIC)-start<UINT64_C(67000000000)) {
            struct pollfd p={.fd=fd,.events=POLLIN};int ready=poll(&p,1,50);if(ready<0 && errno==EINTR)continue;assert(ready>=0);if(!ready)continue;
            for(;;){ssize_t n=recv(fd,data,sizeof(data),MSG_DONTWAIT);if(n<0 && (errno==EAGAIN || errno==EWOULDBLOCK))break;if(n<0 && errno==EINTR)continue;assert(n>=0);uint32_t v=sequence(data,(size_t)n,size);if(!v)invalid++;else if(seen[v])duplicate++;else{seen[v]=1;unique++;}}
        }
        printf("{\"tool\":\"coldwire-lab-udp36\",\"unique\":%u,\"duplicates\":%u,\"invalid\":%u,\"payload\":%zu,\"socket_buffer_bytes\":%d,\"start_wall_ns\":%"PRIu64",\"end_wall_ns\":%"PRIu64"}\n",unique,duplicate,invalid,size,actual,wall,ns(CLOCK_REALTIME));free(seen);
    }
    close(fd);return 0;
}
