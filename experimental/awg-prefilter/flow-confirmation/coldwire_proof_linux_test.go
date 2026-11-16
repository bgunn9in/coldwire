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
	var clock unix.Timespec
	if err = unix.ClockGettime(unix.CLOCK_MONOTONIC, &clock); err != nil {
		t.Fatal(err)
	}
	peer.coldwireProofLast = clock.Nano() + coldwireProofIntervalNS
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
	lastProof, lastReturn, sent := peer.coldwireProofEndpoint, peer.coldwireReturnLast, peer.txBytes.Load()
	peer.coldwireProof(endpoint, keypair, 43)
	if n, _, err = unix.Recvfrom(fd, buffer, 0); err != nil || n != 42 || string(buffer[:4]) != "CWA1" || binary.BigEndian.Uint64(buffer[34:42]) != 43 {
		t.Fatal("valid reordered data did not produce an admission-only event", n, err)
	}
	if peer.coldwireProofEndpoint != lastProof || peer.endpoint.val.DstToString() != changed.DstToString() || peer.coldwireReturnLast != lastReturn || peer.txBytes.Load() != sent {
		t.Fatal("admission-only data rewound the endpoint or triggered recovery")
	}
	peer.coldwireAdmissionLast = clock.Nano() + int64(time.Second)
	peer.coldwireProof(endpoint, keypair, 42)
	if _, _, err = unix.Recvfrom(fd, buffer, 0); err != unix.EAGAIN {
		t.Fatal("admission-only notifications not bounded", err)
	}
	peer.keypairs.current = &Keypair{created: keypair.created.Add(time.Second), localIndex: 2}
	peer.coldwireProof(changed, keypair, 43)
	if _, _, err = unix.Recvfrom(fd, buffer, 0); err != unix.EAGAIN {
		t.Fatal("a non-current keypair produced an admission event", err)
	}
	peer.keypairs.current = keypair
	t.Run("retry-before-notification", func(t *testing.T) {
		coldwireReturns = new(coldwireReturnCache)
		now := time.Now()
		payload := []byte("eligible deferred ciphertext")
		coldwireReturns.remember(coldwireReturnPacket{peer: identity, birth: keypair.created, index: keypair.localIndex, sent: now, payload: payload})
		coldwireReturns.deferReplies(identity, keypair.created, keypair.localIndex, changed.DstToString(), now, now)
		peer.isRunning.Store(true)
		peer.coldwireReturnLast = now.Add(-coldwirePeerReplayInterval)
		var clock unix.Timespec
		if err := unix.ClockGettime(unix.CLOCK_MONOTONIC, &clock); err != nil {
			t.Fatal(err)
		}
		// Keep notifications ineligible while recovery is already due, without a sleep race.
		peer.coldwireProofLast = clock.Nano() + coldwireProofIntervalNS
		lastNotification, sent := peer.coldwireProofLast, peer.txBytes.Load()
		peer.coldwireEndpointCandidate(keypair, 45)
		peer.coldwireProof(changed, keypair, 45)
		if peer.txBytes.Load() != sent+uint64(len(payload)) || coldwireReturns.pending[identity].armed {
			t.Fatal("eligible recovery waited for an unrelated proof notification")
		}
		peer.coldwireEndpointCandidate(keypair, 46)
		peer.coldwireProof(changed, keypair, 46)
		if peer.txBytes.Load() != sent+uint64(len(payload)) {
			t.Fatal("stationary transport rearmed a spent recovery")
		}
		if peer.coldwireProofLast != lastNotification {
			t.Fatal("recovery changed the notification schedule")
		}
		if _, _, err := unix.Recvfrom(fd, buffer, 0); err != unix.EAGAIN {
			t.Fatal("recovery bypassed the notification rate limit", err)
		}
	})
}

func TestColdwireProofIntervalBoundary(t *testing.T) {
	peer := new(Peer)
	if !peer.coldwireProofDue("old", 1000000000) {
		t.Fatal("first event omitted")
	}
	if peer.coldwireProofDue("old", 1009999999) {
		t.Fatal("interval not bounded")
	}
	if !peer.coldwireProofDue("old", 1010000000) {
		t.Fatal("fresh event delayed past 10ms")
	}
	if !peer.coldwireProofDue("new", 1010000001) {
		t.Fatal("movement event delayed")
	}
}

func TestColdwireProofListenerLifecycle(t *testing.T) {
	if os.Geteuid() != 0 {
		t.Skip("root-owned lab socket required")
	}
	path := filepath.Join(t.TempDir(), "events.sock")
	oldReturn := coldwireReturnEnabled
	coldwireReturnEnabled = false
	coldwireProofPath, coldwireProofOnce, coldwireProofFD = path, sync.Once{}, -1
	defer func() {
		if coldwireProofFD >= 0 {
			unix.Close(coldwireProofFD)
		}
		coldwireProofPath, coldwireProofOnce, coldwireProofFD = "", sync.Once{}, -1
		coldwireReturnEnabled = oldReturn
	}()
	peer := new(Peer)
	keypair := &Keypair{created: time.Now(), localIndex: 1}
	peer.keypairs.current = keypair
	endpoint, err := conn.NewDefaultBind().ParseEndpoint("127.0.0.1:32497")
	if err != nil {
		t.Fatal(err)
	}
	send := func(counter uint64) {
		peer.coldwireProofLast = 0
		peer.coldwireEndpointCandidate(keypair, counter)
		peer.coldwireProof(endpoint, keypair, counter)
	}
	// The first authenticated packet arrives before the helper creates its socket.
	send(1)
	listen := func() int {
		fd, err := unix.Socket(unix.AF_UNIX, unix.SOCK_DGRAM|unix.SOCK_NONBLOCK, 0)
		if err != nil {
			t.Fatal(err)
		}
		if err = unix.Bind(fd, &unix.SockaddrUnix{Name: path}); err != nil {
			unix.Close(fd)
			t.Fatal(err)
		}
		if err = os.Chmod(path, 0600); err != nil {
			unix.Close(fd)
			t.Fatal(err)
		}
		return fd
	}
	fd := listen()
	buffer := make([]byte, 128)
	check := func(counter uint64) {
		send(counter)
		n, _, err := unix.Recvfrom(fd, buffer, 0)
		if err != nil || n != 42 || binary.BigEndian.Uint64(buffer[34:42]) != counter {
			t.Fatalf("listener did not recover: n=%d err=%v", n, err)
		}
	}
	check(2)
	unix.Close(fd)
	if err := os.Remove(path); err != nil {
		t.Fatal(err)
	}
	fd = listen()
	defer unix.Close(fd)
	check(3)
	if err := os.Chmod(path, 0666); err != nil {
		t.Fatal(err)
	}
	send(4)
	if _, _, err := unix.Recvfrom(fd, buffer, 0); err != unix.EAGAIN {
		t.Fatal("insecure replacement listener received a proof", err)
	}
	if err := os.Chmod(path, 0600); err != nil {
		t.Fatal(err)
	}
	check(5)
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
