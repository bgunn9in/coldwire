/* SPDX-License-Identifier: MIT */
#define _GNU_SOURCE
#include <assert.h>
#define main prefilter_main
#include "../prefilter.c"
#undef main
int main(void) {
 assert(geteuid()==0);
 FILE *f=fopen("/etc/hostname","r");char name[32]={0};assert(f && fgets(name,sizeof(name),f));fclose(f);assert(!strcmp(name,"kit-entry\n"));
 struct nfq_handle *h=nfq_open();assert(h && !nfq_bind_pf(h,AF_INET));
 size_t original=0;
 struct nfq_q_handle *q=nfq_create_queue(h,54321,callback,&original);assert(q && !nfq_set_mode(q,NFQNL_COPY_META,0));
 int fd=nfq_fd(h);struct timeval timeout={.tv_sec=2};assert(!setsockopt(fd,SOL_SOCKET,SO_RCVTIMEO,&timeout,sizeof(timeout)));
 assert(nfq_set_verdict(q,0xdeadbeef,NF_DROP,0,NULL)>=0);
 char raw[8192] __attribute__((aligned));int n=recv(fd,raw,sizeof(raw),0);assert(n>0 && (unsigned)n>=NLMSG_LENGTH(sizeof(struct nlmsgerr)));
 struct nlmsghdr *header=(struct nlmsghdr *)raw;struct nlmsgerr e;memcpy(&e,NLMSG_DATA(header),sizeof(e));assert(header->nlmsg_type==NLMSG_ERROR && e.error==-ENOENT);
#ifdef COLDWIRE_FIXED36
 int result=handle_datagram(h,raw,n,&original,54321);
#else
 int result=handle_datagram(h,raw,n,&original);
#endif
 printf("{\"real_kernel_error\":%d,\"handler_result\":%d,\"errno_after_handler\":%d,\"queue\":54321,\"no_test_packets\":true}\n",e.error,result,errno);
#ifdef COLDWIRE_FIXED36
 assert(result==0);
#else
 assert(result<0);
#endif
 nfq_destroy_queue(q);nfq_close(h);return 0;
}
