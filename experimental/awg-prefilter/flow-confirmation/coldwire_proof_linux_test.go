// SPDX-License-Identifier: MIT
package device

import (
	"bytes"
	"encoding/binary"
	"os"
	"path/filepath"
	"sync"
	"testing"

	"github.com/amnezia-vpn/amneziawg-go/v3/conn"
	"golang.org/x/sys/unix"
)

func TestColdwireProofLocalEvents(t *testing.T) {
	if os.Geteuid()!=0 { t.Skip("root-owned lab socket required") }
	path:=filepath.Join(t.TempDir(),"events.sock")
	fd,err:=unix.Socket(unix.AF_UNIX,unix.SOCK_DGRAM|unix.SOCK_NONBLOCK,0)
	if err!=nil { t.Fatal(err) };defer unix.Close(fd)
	if err=unix.Bind(fd,&unix.SockaddrUnix{Name:path});err!=nil { t.Fatal(err) }
	if err=os.Chmod(path,0600);err!=nil { t.Fatal(err) }
	coldwireProofPath=path;coldwireProofOnce=sync.Once{};coldwireProofFD=-1
	defer func(){if coldwireProofFD>=0 {unix.Close(coldwireProofFD)};coldwireProofFD=-1;coldwireProofPath=""}()
	endpoint,err:=conn.NewDefaultBind().ParseEndpoint("127.0.0.1:32497")
	if err!=nil { t.Fatal(err) }
	peer:=new(Peer);peer.coldwireProof(endpoint,42)
	buffer:=make([]byte,128);n,_,err:=unix.Recvfrom(fd,buffer,0)
	if err!=nil || n!=42 || !bytes.Equal(buffer[:4],[]byte("CWP1")) || binary.BigEndian.Uint64(buffer[34:42])!=42 {t.Fatalf("invalid event n=%d err=%v",n,err)}
	peer.coldwireProof(endpoint,43)
	if _,_,err=unix.Recvfrom(fd,buffer,0);err!=unix.EAGAIN {t.Fatal("same-endpoint notifications not bounded",err)}
	changed,err:=conn.NewDefaultBind().ParseEndpoint("127.0.0.1:42501");if err!=nil {t.Fatal(err)}
	peer.coldwireProof(changed,44)
	if n,_,err=unix.Recvfrom(fd,buffer,0);err!=nil || n!=42 || binary.BigEndian.Uint16(buffer[16:18])!=42501 {t.Fatal("source-port move not reported",n,err)}
}
