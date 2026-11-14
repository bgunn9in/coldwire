// SPDX-License-Identifier: MIT
package device

import (
	"bytes"
	"crypto/sha256"
	"net"
	"sync"
	"testing"
	"time"

	"github.com/amnezia-vpn/amneziawg-go/v3/conn"
	"github.com/amnezia-vpn/amneziawg-go/v3/tun/tuntest"
)

func TestColdwireDeferredSnapshotRetargetAndOneAttemptPerMove(t *testing.T) {
	cache := new(coldwireReturnCache)
	now := time.Now()
	id := [32]byte{1}
	cache.remember(coldwireReturnPacket{peer: id, birth: now, index: 1, sent: now, payload: []byte("ciphertext")})
	cache.deferReplies(id, now, 1, "old", now, now.Add(time.Second))
	cache.packets[cache.head].payload[0] = 'X'
	original := cache.pending[id]
	if got := cache.takePending(id, now, 1, "old", now.Add(999*time.Millisecond)); len(got) != 0 {
		t.Fatal("pending reply escaped its cooldown")
	}
	if !cache.retargetPending(id, now, 1, "latest", now.Add(250*time.Millisecond)) {
		t.Fatal("the latest authenticated move did not replace the target")
	}
	value := cache.pending[id]
	if value.due != original.due || value.expires != original.expires || &value.buffers[0][0] != &original.buffers[0][0] {
		t.Fatal("retarget extended lifetime or allocated another snapshot")
	}
	cache.prune(now.Add(coldwireReturnAge))
	if cache.count != 0 {
		t.Fatal("the ordinary ring did not expire")
	}
	got := cache.takePending(id, now, 1, "latest", now.Add(time.Second))
	if len(got) != 1 || !bytes.Equal(got[0], []byte("ciphertext")) {
		t.Fatal("the bounded snapshot did not survive ring expiry or input reuse")
	}
	if cache.pendingBytes != len("ciphertext") || cache.pendingPackets != 1 || len(cache.pending) != 1 || cache.pending[id].armed {
		t.Fatal("the spent attempt lost its bounded snapshot or remained armed")
	}
	if len(cache.takePending(id, now, 1, "latest", now.Add(time.Second))) != 0 {
		t.Fatal("one pending move produced multiple attempts")
	}
	cache.prunePending(now.Add(coldwirePendingAge))
	if cache.pendingBytes != 0 || cache.pendingPackets != 0 || len(cache.pending) != 0 {
		t.Fatal("the original deadline did not release the spent snapshot")
	}
}

func TestColdwireHeldSnapshotRequiresMoveAndMergesNewReplies(t *testing.T) {
	cache := new(coldwireReturnCache)
	now := time.Now()
	id := [32]byte{1}
	remember := func(payload string, stamp time.Time) {
		cache.remember(coldwireReturnPacket{peer: id, birth: now, index: 1, sent: stamp, payload: []byte(payload)})
	}
	remember("first", now)
	buffers, through := cache.selectReplies(id, now, 1, now)
	remember("between select and hold", now.Add(time.Millisecond))
	cache.holdReplies(id, now, 1, "first target", now, through, buffers)
	original := cache.pending[id]
	if &original.buffers[0][0] != &buffers[0][0] {
		t.Fatal("holding the selected snapshot copied its ciphertext")
	}
	if len(cache.takePending(id, now, 1, "first target", now.Add(coldwirePeerReplayInterval))) != 0 {
		t.Fatal("stationary traffic armed another replay")
	}
	cache.retargetPending(id, now, 1, "second", now.Add(250*time.Millisecond))
	remember("third path", now.Add(350*time.Millisecond))
	cache.retargetPending(id, now, 1, "latest", now.Add(400*time.Millisecond))
	cache.retargetPending(id, now, 1, "latest", now.Add(450*time.Millisecond))
	value := cache.pending[id]
	if value.expires != original.expires || value.due != original.due || len(value.buffers) != 3 {
		t.Fatal("retarget extended the lifetime, duplicated overlap or lost newly sent ciphertext")
	}
	got := cache.takePending(id, now, 1, "latest", now.Add(500*time.Millisecond))
	if len(got) != 3 || string(got[0]) != "first" || string(got[1]) != "between select and hold" || string(got[2]) != "third path" {
		t.Fatal("merged snapshot order or selection watermark failed")
	}
	if cache.pendingPackets != 3 || cache.pending[id].armed {
		t.Fatal("the spent merged snapshot was lost or remained armed")
	}
	remember("fourth path", now.Add(650*time.Millisecond))
	cache.retargetPending(id, now, 1, "fourth", now.Add(700*time.Millisecond))
	got = cache.takePending(id, now, 1, "fourth", now.Add(750*time.Millisecond))
	if len(got) != 4 || string(got[0]) != "first" || string(got[3]) != "fourth path" || cache.pending[id].expires != original.expires {
		t.Fatal("another authenticated move lost earlier ciphertext or renewed its deadline")
	}
}

func TestColdwireHeldAndMergedGlobalBudgets(t *testing.T) {
	now := time.Now()
	id := [32]byte{1}
	for _, size := range []int{1, 65536} {
		cache := new(coldwireReturnCache)
		buffers := make([][]byte, coldwirePendingPackets)
		count := min(coldwirePendingPackets, coldwirePendingBytes/size)
		for i := 0; i < count; i++ {
			buffers[i] = make([]byte, size)
		}
		buffers = buffers[:count]
		cache.holdReplies(id, now, 1, "old", now, 0, buffers)
		cache.holdReplies([32]byte{2}, now, 1, "other", now, 0, [][]byte{make([]byte, size)})
		cache.remember(coldwireReturnPacket{peer: id, birth: now, index: 1, sent: now, payload: make([]byte, size)})
		cache.retargetPending(id, now, 1, "latest", now.Add(time.Millisecond))
		if len(cache.pending) != 1 || cache.pendingPackets != count || cache.pendingBytes != count*size {
			t.Fatal("holding or merging bypassed a shared packet/byte budget")
		}
		cache.prunePending(now.Add(coldwirePendingAge))
		if len(cache.pending) != 0 || cache.pendingPackets != 0 || cache.pendingBytes != 0 {
			t.Fatal("unused held snapshot was retained after expiry")
		}
	}
}

func TestColdwireDeferredOwnershipExpiryAndBounds(t *testing.T) {
	now := time.Now()
	id := [32]byte{1}
	for _, kind := range []string{"epoch", "index", "address", "expiry"} {
		cache := new(coldwireReturnCache)
		cache.remember(coldwireReturnPacket{peer: id, birth: now, index: 1, sent: now, payload: []byte{1}})
		cache.deferReplies(id, now, 1, "current", now, now)
		birth, index, address, stamp := now, uint32(1), "current", now
		switch kind {
		case "epoch":
			birth = now.Add(time.Second)
		case "index":
			index++
		case "address":
			address = "obsolete"
		case "expiry":
			stamp = now.Add(coldwirePendingAge)
		}
		if len(cache.takePending([32]byte{2}, birth, index, address, stamp)) != 0 {
			t.Fatal("another peer consumed the snapshot")
		}
		if len(cache.takePending(id, birth, index, address, stamp)) != 0 || cache.pendingBytes != 0 || cache.pendingPackets != 0 {
			t.Fatalf("%s did not discard pending ciphertext", kind)
		}
	}
	cache := new(coldwireReturnCache)
	for i := 0; i < coldwireReturnSlots; i++ {
		cache.remember(coldwireReturnPacket{peer: id, birth: now, index: 1, sent: now, payload: []byte{1}})
	}
	cache.deferReplies(id, now, 1, "current", now, now)
	if cache.pendingPackets != coldwirePendingPackets || cache.pendingBytes != coldwirePendingPackets {
		t.Fatal("global pending packet budget failed")
	}
	cache.prunePending(now.Add(coldwirePendingAge))
	if cache.pendingBytes != 0 || cache.pendingPackets != 0 {
		t.Fatal("idle expiry did not release snapshot references and budget")
	}
	cache = new(coldwireReturnCache)
	for i := 0; i < 64; i++ {
		cache.remember(coldwireReturnPacket{peer: id, birth: now, index: 1, sent: now, payload: make([]byte, 65536)})
	}
	cache.deferReplies(id, now, 1, "current", now, now)
	if cache.pendingBytes != coldwirePendingBytes || cache.pendingPackets != coldwirePendingBytes/65536 {
		t.Fatal("global pending byte budget failed")
	}
	cache = new(coldwireReturnCache)
	for i := 0; i <= coldwirePendingPeers; i++ {
		identity := [32]byte{byte(i)}
		cache.remember(coldwireReturnPacket{peer: identity, birth: now, index: 1, sent: now, payload: []byte{1}})
		cache.deferReplies(identity, now, 1, "current", now, now)
	}
	if len(cache.pending) != coldwirePendingPeers {
		t.Fatal("global pending peer budget failed")
	}
}

func TestColdwireDeferredGlobalSpacing(t *testing.T) {
	cache := new(coldwireReturnCache)
	now := time.Now()
	cache.lastReplay = now
	for i := 1; i <= 2; i++ {
		id := [32]byte{byte(i)}
		cache.remember(coldwireReturnPacket{peer: id, birth: now, index: 1, sent: now, payload: []byte{1}})
		cache.deferReplies(id, now, 1, "current", now, now)
	}
	if len(cache.takePending([32]byte{1}, now, 1, "current", now.Add(249*time.Millisecond))) != 0 {
		t.Fatal("global cooldown was bypassed")
	}
	if len(cache.takePending([32]byte{1}, now, 1, "current", now.Add(250*time.Millisecond))) != 1 {
		t.Fatal("eligible pending attempt was lost")
	}
	if len(cache.takePending([32]byte{2}, now, 1, "current", now.Add(499*time.Millisecond))) != 0 {
		t.Fatal("two pending peers bypassed global spacing")
	}
	if len(cache.takePending([32]byte{2}, now, 1, "current", now.Add(500*time.Millisecond))) != 1 {
		t.Fatal("the second eligible pending attempt was lost")
	}
}

func TestColdwireDeferredConcurrentPruning(t *testing.T) {
	cache := new(coldwireReturnCache)
	birth := time.Now()
	id := [32]byte{1}
	var workers sync.WaitGroup
	for worker := 0; worker < 3; worker++ {
		workers.Add(1)
		go func(worker int) {
			defer workers.Done()
			for i := 0; i < 1000; i++ {
				now := time.Now()
				switch worker {
				case 0:
					cache.remember(coldwireReturnPacket{peer: id, birth: birth, index: 1, sent: now, payload: []byte("ciphertext")})
					cache.deferReplies(id, birth, 1, "current", now, now)
					cache.retargetPending(id, birth, 1, "latest", now)
				case 1:
					cache.takePending(id, birth, 1, "latest", now)
					cache.cancelPending(id)
				case 2:
					cache.Lock()
					cache.prunePending(now)
					cache.Unlock()
				}
			}
		}(worker)
	}
	workers.Wait()
	cache.prunePending(time.Now().Add(coldwirePendingAge))
	if len(cache.pending) != 0 || cache.pendingBytes != 0 || cache.pendingPackets != 0 {
		t.Fatal("concurrent queue/take/prune leaked pending budget")
	}
}

func TestColdwireDeferredRuntimeGuards(t *testing.T) {
	oldEnabled, oldCache := coldwireReturnEnabled, coldwireReturns
	coldwireReturnEnabled, coldwireReturns = true, new(coldwireReturnCache)
	coldwireReturnOnce = sync.Once{}
	coldwireReturnOnce.Do(func() {})
	t.Cleanup(func() {
		coldwireReturnEnabled, coldwireReturns = oldEnabled, oldCache
		coldwireReturnOnce = sync.Once{}
	})
	first, err := net.ListenUDP("udp4", &net.UDPAddr{IP: net.IPv4(127, 0, 0, 1)})
	if err != nil {
		t.Fatal(err)
	}
	defer first.Close()
	latest, err := net.ListenUDP("udp4", &net.UDPAddr{IP: net.IPv4(127, 0, 0, 1)})
	if err != nil {
		t.Fatal(err)
	}
	defer latest.Close()
	bind := conn.NewDefaultBind()
	if _, _, err = bind.Open(0); err != nil {
		t.Fatal(err)
	}
	defer bind.Close()
	a, _ := bind.ParseEndpoint(first.LocalAddr().String())
	b, _ := bind.ParseEndpoint(latest.LocalAddr().String())
	peer := new(Peer)
	peer.device = new(Device)
	peer.device.net.bind = bind
	peer.device.log = NewLogger(LogLevelSilent, "")
	peer.isRunning.Store(true)
	peer.endpoint.val = b
	now := time.Now()
	key := &Keypair{created: now, localIndex: 1}
	peer.keypairs.current = key
	id := [32]byte{1}
	remember := func() {
		coldwireReturns.remember(coldwireReturnPacket{peer: id, birth: now, index: 1, sent: time.Now(), payload: []byte("ciphertext")})
		coldwireReturns.deferReplies(id, now, 1, a.DstToString(), time.Now(), time.Now())
	}
	remember()
	peer.coldwireRetryReplies(id, key, b)
	if len(coldwireReturns.pending) != 0 {
		t.Fatal("obsolete target retained")
	}
	remember()
	peer.coldwireRetryReplies(id, key, a)
	if len(coldwireReturns.pending) != 0 || !peer.coldwireReturnLast.IsZero() {
		t.Fatal("a callback for an obsolete endpoint consumed a send attempt")
	}
	peer.endpoint.val = a
	for _, kind := range []string{"stop", "roaming", "key", "device"} {
		remember()
		switch kind {
		case "stop":
			peer.isRunning.Store(false)
		case "roaming":
			peer.endpoint.disableRoaming = true
		case "key":
			peer.keypairs.current = &Keypair{created: now.Add(time.Second), localIndex: 2}
		case "device":
			peer.device.state.state.Store(uint32(deviceStateClosed))
		}
		peer.coldwireRetryReplies(id, key, a)
		if len(coldwireReturns.pending) != 0 || peer.txBytes.Load() != 0 || !peer.coldwireReturnLast.IsZero() {
			t.Fatalf("%s allowed deferred send", kind)
		}
		peer.isRunning.Store(true)
		peer.endpoint.disableRoaming = false
		peer.keypairs.current = key
		peer.device.state.state.Store(uint32(deviceStateDown))
	}
	peer.endpoint.val = b
	remember()
	coldwireReturns.retargetPending(id, now, 1, b.DstToString(), time.Now())
	coldwireReplaySending.Lock()
	peer.coldwireRetryReplies(id, key, b)
	coldwireReplaySending.Unlock()
	if len(coldwireReturns.pending) != 1 || peer.txBytes.Load() != 0 {
		t.Fatal("a busy sender consumed or sent the pending snapshot")
	}
	peer.coldwireReturnLast = time.Now()
	peer.coldwireRetryReplies(id, key, b)
	if len(coldwireReturns.pending) != 1 || peer.txBytes.Load() != 0 {
		t.Fatal("the per-peer cooldown allowed an early send")
	}
	peer.coldwireReturnLast = time.Now().Add(-coldwirePeerReplayInterval)
	peer.coldwireRetryReplies(id, key, b)
	buffer := make([]byte, 64)
	latest.SetReadDeadline(time.Now().Add(time.Second))
	if n, _, err := latest.ReadFromUDP(buffer); err != nil || string(buffer[:n]) != "ciphertext" {
		t.Fatal("latest target did not receive snapshot", err)
	}
	first.SetReadDeadline(time.Now().Add(20 * time.Millisecond))
	if _, _, err := first.ReadFromUDP(buffer); err == nil {
		t.Fatal("obsolete target received snapshot")
	}
}

func TestColdwireDeferredEncryptedLossAndNoDuplicate(t *testing.T) {
	oldEnabled, oldCache := coldwireReturnEnabled, coldwireReturns
	coldwireReturnEnabled, coldwireReturns = true, new(coldwireReturnCache)
	coldwireReturnOnce = sync.Once{}
	coldwireReturnOnce.Do(func() {})
	t.Cleanup(func() {
		coldwireReturnEnabled, coldwireReturns = oldEnabled, oldCache
		coldwireReturnOnce = sync.Once{}
	})
	pair := genTestPair(t, true)
	pair.Send(t, Ping, nil)
	sender := pair[1].dev
	var peer *Peer
	sender.peers.RLock()
	for _, value := range sender.peers.keyMap {
		peer = value
	}
	sender.peers.RUnlock()
	if peer == nil {
		t.Fatal("missing peer")
	}
	sender.net.Lock()
	original := sender.net.bind
	drop := &coldwireDropBind{Bind: original, dropped: make(chan struct{})}
	sender.net.bind = drop
	sender.net.Unlock()
	message := tuntest.Ping(pair[0].ip, pair[1].ip)
	message[len(message)-1] ^= 1
	pair[1].tun.Outbound <- message
	select {
	case <-drop.dropped:
	case <-time.After(time.Second):
		t.Fatal("no deliberate ciphertext drop")
	}
	sender.net.Lock()
	sender.net.bind = original
	sender.net.Unlock()
	peer.endpoint.Lock()
	endpoint := peer.endpoint.val
	peer.endpoint.Unlock()
	peer.handshake.mutex.RLock()
	id := sha256.Sum256(peer.handshake.remoteStatic[:])
	peer.handshake.mutex.RUnlock()
	key := peer.keypairs.Current()
	peer.coldwireReturnLast = time.Now()
	peer.coldwireReplayReplies(id, key, endpoint)
	if len(coldwireReturns.pending) != 1 {
		t.Fatal("cooldown did not preserve a bounded snapshot")
	}
	select {
	case <-pair[0].tun.Inbound:
		t.Fatal("deferred ciphertext arrived before cooldown")
	case <-time.After(20 * time.Millisecond):
	}
	deadline := peer.coldwireReturnLast.Add(coldwireReturnAge + 20*time.Millisecond)
	for time.Now().Before(deadline) {
		time.Sleep(5 * time.Millisecond)
	}
	coldwireReturns.Lock()
	coldwireReturns.prune(time.Now())
	coldwireReturns.Unlock()
	// Simulate the next authenticated callback after cooldown and ordinary ring expiry.
	peer.coldwireRetryReplies(id, key, endpoint)
	select {
	case got := <-pair[0].tun.Inbound:
		if !bytes.Equal(got, message) {
			t.Fatal("deferred plaintext changed")
		}
	case <-time.After(time.Second):
		t.Fatal("deferred ciphertext did not recover plaintext after ring expiry")
	}
	drop = &coldwireDropBind{Bind: original, dropped: make(chan struct{})}
	sender.net.Lock()
	sender.net.bind = drop
	sender.net.Unlock()
	second := append([]byte(nil), message...)
	second[len(second)-1] ^= 2
	pair[1].tun.Outbound <- second
	select {
	case <-drop.dropped:
	case <-time.After(time.Second):
		t.Fatal("no deliberate second ciphertext drop")
	}
	sender.net.Lock()
	sender.net.bind = original
	sender.net.Unlock()
	coldwireReturns.retargetPending(id, key.created, key.localIndex, endpoint.DstToString(), time.Now())
	time.Sleep(coldwirePeerReplayInterval + 10*time.Millisecond)
	peer.coldwireRetryReplies(id, key, endpoint)
	select {
	case got := <-pair[0].tun.Inbound:
		if !bytes.Equal(got, second) {
			t.Fatal("another recovery delivered old plaintext instead of the new lost packet")
		}
	case <-time.After(time.Second):
		t.Fatal("another authenticated move did not recover its new ciphertext")
	}
	peer.coldwireRetryReplies(id, key, endpoint)
	select {
	case <-pair[0].tun.Inbound:
		t.Fatal("deferred snapshot duplicated plaintext")
	case <-time.After(30 * time.Millisecond):
	}
}
