// SPDX-License-Identifier: MIT
package device

import (
	"bytes"
	"crypto/sha256"
	"encoding/binary"
	"os"
	"path/filepath"
	"sync"
	"testing"
	"time"

	"github.com/amnezia-vpn/amneziawg-go/v3/conn"
	"golang.org/x/sys/unix"
)

type coldwireSnapshotBind struct {
	conn.Bind
	peer                     *Peer
	keypair                  *Keypair
	injected                 bool
	afterSnapshotDestination string
}

func (bind *coldwireSnapshotBind) Send(_ [][]byte, endpoint conn.Endpoint) error {
	if bind.injected {
		bind.afterSnapshotDestination = endpoint.DstToString()
		return nil
	}
	bind.injected = true
	later := []byte("created after the recovery snapshot")
	bind.peer.coldwireRememberReply(later, bind.keypair)
	return bind.peer.SendBuffers([][]byte{later})
}

func TestColdwireProofLocalEvents(t *testing.T) {
	if os.Geteuid() != 0 {
		t.Skip("root-owned lab socket required")
	}
	path := filepath.Join(t.TempDir(), "events.sock")
	fd, err := unix.Socket(unix.AF_UNIX, unix.SOCK_DGRAM|unix.SOCK_NONBLOCK, 0)
	if err != nil {
		t.Fatal(err)
	}
	defer unix.Close(fd)
	if err = unix.Bind(fd, &unix.SockaddrUnix{Name: path}); err != nil {
		t.Fatal(err)
	}
	if err = os.Chmod(path, 0600); err != nil {
		t.Fatal(err)
	}
	coldwireProofPath = path
	oldReturnEnabled, oldCache := coldwireReturnEnabled, coldwireReturns
	coldwireReturnEnabled, coldwireReturns = true, new(coldwireReturnCache)
	coldwireReturnOnce = sync.Once{}
	coldwireReturnOnce.Do(func() {})
	defer func() {
		coldwireReturnEnabled, coldwireReturns = oldReturnEnabled, oldCache
		coldwireReturnOnce = sync.Once{}
	}()
	coldwireProofOnce = sync.Once{}
	coldwireProofFD = -1
	defer func() {
		if coldwireProofFD >= 0 {
			unix.Close(coldwireProofFD)
		}
		coldwireProofFD = -1
		coldwireProofPath = ""
	}()
	endpoint, err := conn.NewDefaultBind().ParseEndpoint("127.0.0.1:32497")
	if err != nil {
		t.Fatal(err)
	}
	peer := new(Peer)
	keypair := &Keypair{created: time.Now(), localIndex: 1}
	peer.keypairs.current = keypair
	peer.coldwireEndpointCandidate(keypair, 42)
	peer.coldwireCommitEndpoint(endpoint, keypair, 42)
	peer.coldwireProof(endpoint, keypair, 42)
	buffer := make([]byte, 128)
	n, _, err := unix.Recvfrom(fd, buffer, 0)
	if err != nil || n != 42 || !bytes.Equal(buffer[:4], []byte("CWP1")) || binary.BigEndian.Uint64(buffer[34:42]) != 42 {
		t.Fatalf("invalid event n=%d err=%v", n, err)
	}
	peer.coldwireEndpointCandidate(keypair, 43)
	peer.coldwireProof(endpoint, keypair, 43)
	if _, _, err = unix.Recvfrom(fd, buffer, 0); err != unix.EAGAIN {
		t.Fatal("same-endpoint notifications not bounded", err)
	}
	changed, err := conn.NewDefaultBind().ParseEndpoint("127.0.0.1:42501")
	if err != nil {
		t.Fatal(err)
	}
	peer.device = new(Device)
	bind := &coldwireSnapshotBind{Bind: conn.NewDefaultBind(), peer: peer, keypair: keypair}
	peer.device.net.bind = bind
	peer.device.log = NewLogger(LogLevelSilent, "")
	identity := sha256.Sum256(peer.handshake.remoteStatic[:])
	coldwireReturns.remember(coldwireReturnPacket{peer: identity, birth: keypair.created, index: keypair.localIndex, sent: time.Now(), payload: []byte("old ciphertext")})
	peer.coldwireEndpointCandidate(keypair, 44)
	peer.coldwireProof(changed, keypair, 44)
	if bind.afterSnapshotDestination != changed.DstToString() {
		t.Fatal("packet created after recovery snapshot used the old endpoint", bind.afterSnapshotDestination)
	}
	if n, _, err = unix.Recvfrom(fd, buffer, 0); err != nil || n != 42 || binary.BigEndian.Uint16(buffer[16:18]) != 42501 {
		t.Fatal("source-port move not reported", n, err)
	}
	peer.coldwireProof(endpoint, keypair, 43)
	if _, _, err = unix.Recvfrom(fd, buffer, 0); err != unix.EAGAIN {
		t.Fatal("late old endpoint generated a fresh proof", err)
	}
}

func TestColdwireProofIntervalBoundary(t *testing.T) {
	peer := new(Peer)
	if !peer.coldwireProofDue("old", 1000000000) {
		t.Fatal("first event omitted")
	}
	if peer.coldwireProofDue("old", 1049999999) {
		t.Fatal("interval not bounded")
	}
	if !peer.coldwireProofDue("old", 1050000000) {
		t.Fatal("fresh event delayed past 50ms")
	}
	if !peer.coldwireProofDue("new", 1050000001) {
		t.Fatal("movement event delayed")
	}
}

func TestColdwireEndpointReorderAndKeyRotation(t *testing.T) {
	peer := new(Peer)
	oldEndpoint, _ := conn.NewDefaultBind().ParseEndpoint("127.0.0.1:32497")
	newEndpoint, _ := conn.NewDefaultBind().ParseEndpoint("127.0.0.1:42501")
	oldKey := &Keypair{created: time.Now(), localIndex: 7}
	peer.keypairs.current = oldKey
	if !peer.coldwireEndpointCandidate(oldKey, 100) {
		t.Fatal("first counter not selected")
	}
	peer.coldwireCommitEndpoint(oldEndpoint, oldKey, 100)
	if !peer.coldwireEndpointCandidate(oldKey, 102) {
		t.Fatal("new endpoint not selected")
	}
	if peer.coldwireEndpointCandidate(oldKey, 101) || peer.coldwireEndpointCandidate(oldKey, 102) {
		t.Fatal("late/duplicate counter selected")
	}
	peer.coldwireCommitEndpoint(oldEndpoint, oldKey, 101)
	peer.coldwireCommitEndpoint(newEndpoint, oldKey, 102)
	if peer.endpoint.val.DstToString() != "127.0.0.1:42501" {
		t.Fatal("batch tail rewound endpoint")
	}
	peer.coldwireCommitEndpoint(oldEndpoint, oldKey, 100)
	if peer.endpoint.val.DstToString() != "127.0.0.1:42501" {
		t.Fatal("late commit rewound endpoint")
	}
	newKey := &Keypair{created: oldKey.created.Add(time.Second), localIndex: 8}
	peer.keypairs.current = newKey
	if !peer.coldwireEndpointCandidate(newKey, 0) {
		t.Fatal("new-key counter zero rejected")
	}
	peer.coldwireCommitEndpoint(newEndpoint, newKey, 0)
	if peer.coldwireEndpointCandidate(oldKey, 1000) {
		t.Fatal("old key rewound epoch")
	}
	peer.coldwireCommitEndpoint(oldEndpoint, oldKey, 1000)
	if peer.endpoint.val.DstToString() != "127.0.0.1:42501" {
		t.Fatal("old-key endpoint committed")
	}
	peer.endpoint.disableRoaming = true
	if !peer.coldwireEndpointCandidate(newKey, 1) {
		t.Fatal("new counter not selected")
	}
	peer.coldwireCommitEndpoint(oldEndpoint, newKey, 1)
	if peer.endpoint.val.DstToString() != "127.0.0.1:42501" {
		t.Fatal("disabled roaming ignored")
	}
	if peer.coldwireEndpointCandidate(nil, 2) {
		t.Fatal("nil key selected")
	}
}
