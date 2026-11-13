"""Compile the actual QEMU socket send function with bounded fake I/O."""
import argparse
from pathlib import Path
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source', required=True, type=Path)
    parser.add_argument('--workdir', required=True, type=Path)
    parser.add_argument('--cc', default='gcc')
    args = parser.parse_args()
    text = args.source.read_text(encoding='utf-8')
    start = text.index('static ssize_t net_socket_receive(')
    end = text.index('\n}\n', start)+3
    function = text[start:end]
    prefix = r'''
#include <assert.h>
#include <errno.h>
#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/types.h>
#define CONFIG_WIN32 1
typedef struct { int unused; } NetClientState;
typedef struct { NetClientState nc; int fd; unsigned send_index; } NetSocketState;
#define DO_UPCAST(type, field, ptr) ((type *)((char *)(ptr)-offsetof(type, field)))
struct iovec { void *iov_base; size_t iov_len; };
static unsigned calls, polls, allocations;
static ssize_t next_return = -2;
static unsigned char received[80000];
static size_t received_length;
static uint32_t htonl(uint32_t n) {
    const unsigned char bytes[] = {n>>24,n>>16,n>>8,n};
    uint32_t out; memcpy(&out,bytes,4); return out;
}
static __attribute__((unused)) void *g_malloc(size_t size) { allocations++; void *p=malloc(size); assert(p); return p; }
static void __attribute__((unused)) cleanup(void *value) { void **p=value; if (*p) { free(*p); allocations--; } }
#define g_autofree __attribute__((cleanup(cleanup)))
static size_t iov_size(struct iovec *v, unsigned count) { size_t n=0; for(unsigned i=0;i<count;i++)n+=v[i].iov_len; return n; }
static ssize_t mock_send(int fd, const void *data, size_t size, int flags) {
    assert(fd==42 && flags==0); calls++;
    ssize_t value=next_return; next_return=-2;
    if(value==-1)return -1;
    size_t count=value==-2?size:(size_t)value;
    assert(count<=size && received_length+count<=sizeof(received));
    memcpy(received+received_length,data,count);received_length+=count;
    return (ssize_t)count;
}
#define send mock_send
static inline ssize_t iov_send(int fd, struct iovec *v, unsigned count, size_t offset, size_t remaining) {
    ssize_t sent=0;
    for(unsigned i=0;i<count && remaining;i++) {
        if(offset>=v[i].iov_len){offset-=v[i].iov_len;continue;}
        size_t size=v[i].iov_len-offset;if(size>remaining)size=remaining;
        ssize_t n=mock_send(fd,(unsigned char *)v[i].iov_base+offset,size,0);
        if(n<0)return sent?sent:n;
        sent+=n;if((size_t)n<size)return sent;
        remaining-=size;offset=0;
    }
    return sent;
}
static void net_socket_write_poll(NetSocketState *s, bool value) { assert(s->fd==42 && value); polls++; }
'''
    suffix = r'''
static void reset(void) { assert(!allocations);calls=polls=0;received_length=0;next_return=-2; }
static void exact(const unsigned char *payload, size_t size) {
    assert(received_length==size+4);
    uint32_t n=htonl((uint32_t)size);assert(!memcmp(received,&n,4));
    assert(!memcmp(received+4,payload,size) && !allocations);
}
int main(void) {
    unsigned char payload[69632];for(size_t i=0;i<sizeof(payload);i++)payload[i]=(unsigned char)i;
    NetSocketState s={.fd=42};
    reset();assert(net_socket_receive(&s.nc,payload,37)==37);assert(calls==1 && polls==0 && !s.send_index);exact(payload,37);
    reset();next_return=2;assert(net_socket_receive(&s.nc,payload,37)==0 && s.send_index==2 && polls==1);
    next_return=7;assert(net_socket_receive(&s.nc,payload,37)==0 && s.send_index==9);
    errno=EAGAIN;next_return=-1;assert(net_socket_receive(&s.nc,payload,37)==0 && s.send_index==9);
    assert(net_socket_receive(&s.nc,payload,37)==37 && !s.send_index && calls==4);exact(payload,37);
    reset();next_return=0;assert(net_socket_receive(&s.nc,payload,37)==0 && !s.send_index && polls==1);
    assert(net_socket_receive(&s.nc,payload,37)==37);exact(payload,37);
    reset();next_return=3;assert(net_socket_receive(&s.nc,payload,37)==0 && s.send_index==3);
    errno=EIO;next_return=-1;assert(net_socket_receive(&s.nc,payload,37)==-EIO && !s.send_index && !allocations);
    reset();assert(net_socket_receive(&s.nc,payload,0)==0);exact(payload,0);
    reset();assert(net_socket_receive(&s.nc,payload,sizeof(payload))==(ssize_t)sizeof(payload));
    assert(calls==1 && !s.send_index);exact(payload,sizeof(payload));
    puts("PASS single-write framing, partial retries, EAGAIN, zero send, fatal error, zero/max payload and cleanup");
}
'''
    work = args.workdir.resolve()
    work.mkdir(parents=True, exist_ok=True)
    source = work / 'qemu-stream-test.c'
    binary = work / 'qemu-stream-test.exe'
    source.write_text(prefix+function+suffix, encoding='utf-8')
    subprocess.run([args.cc, '-O2', '-std=c11', '-Wall', '-Wextra', '-Werror',
                    '-static-libgcc', str(source), '-o', str(binary)], check=True)
    subprocess.run([str(binary)], check=True, cwd=work)


if __name__ == '__main__':
    main()
