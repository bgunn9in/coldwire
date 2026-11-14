// SPDX-License-Identifier: MIT
package device

import (
	"bytes"
	"crypto/sha256"
	"encoding/binary"
	"net"
	"sync"
	"testing"
	"time"

	"github.com/amnezia-vpn/amneziawg-go/v3/conn"
	"github.com/amnezia-vpn/amneziawg-go/v3/tun/tuntest"
)

func TestColdwireReturnIsolationExpiryAndOwnership(t *testing.T) {
	cache := new(coldwireReturnCache)
	now := time.Now()
	identity := [32]byte{1}
	data := []byte("encrypted reply")
	cache.remember(coldwireReturnPacket{peer: identity, birth: now, index: 7, sent: now, payload: data})
	data[0] = 'X'
	if got := cache.selectReplies([32]byte{2}, now, 7, now); len(got) != 0 {
		t.Fatal("another peer received ciphertext")
	}
	if got := cache.selectReplies(identity, now.Add(time.Second), 7, now); len(got) != 0 {
		t.Fatal("another epoch received ciphertext")
	}
	if got := cache.selectReplies(identity, now, 8, now); len(got) != 0 {
		t.Fatal("another key index received ciphertext")
	}
	got := cache.selectReplies(identity, now, 7, now)
	if len(got) != 1 || !bytes.Equal(got[0], []byte("encrypted reply")) {
		t.Fatal("pooled input buffer retained")
	}
	got[0][0] = 'Y'
	if got := cache.selectReplies(identity, now, 7, now.Add(249*time.Millisecond)); len(got) != 0 {
		t.Fatal("global replay frequency unbounded")
	}
	got = cache.selectReplies(identity, now, 7, now.Add(250*time.Millisecond))
	if len(got) != 1 || got[0][0] != 'e' {
		t.Fatal("replay write modified cached ciphertext")
	}
	if got := cache.selectReplies(identity, now, 7, now.Add(coldwireReturnAge)); len(got) != 0 || cache.count != 0 || cache.bytes != 0 {
		t.Fatal("expired ciphertext retained")
	}
	for _, packet := range cache.packets {
		if packet.payload != nil {
			t.Fatal("expired reference retained")
		}
	}
}

type coldwireDropBind struct {
	conn.Bind
	dropped chan struct{}
	once    sync.Once
}

func (bind *coldwireDropBind) Send(_ [][]byte, _ conn.Endpoint) error {
	bind.once.Do(func() { close(bind.dropped) })
	return nil
}

func TestColdwireReturnLostCiphertextAndDuplicateDelivery(t *testing.T) {
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
		t.Fatal("missing test peer")
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
		t.Fatal("no ciphertext reached the deliberate drop")
	}
	sender.net.Lock()
	sender.net.bind = original
	sender.net.Unlock()
	select {
	case <-pair[0].tun.Inbound:
		t.Fatal("deliberately dropped ciphertext arrived")
	case <-time.After(20 * time.Millisecond):
	}
	peer.endpoint.Lock()
	endpoint := peer.endpoint.val
	peer.endpoint.Unlock()
	peer.handshake.mutex.RLock()
	identity := sha256.Sum256(peer.handshake.remoteStatic[:])
	peer.handshake.mutex.RUnlock()
	peer.coldwireReplayReplies(identity, peer.keypairs.Current(), endpoint)
	select {
	case got := <-pair[0].tun.Inbound:
		if !bytes.Equal(message, got) {
			t.Fatal("recovered payload changed")
		}
	case <-time.After(time.Second):
		t.Fatal("cached ciphertext did not recover the lost payload")
	}
	// The same cached ciphertext must not produce a second plaintext delivery.
	peer.coldwireReturnLast = time.Time{}
	coldwireReturns.Lock()
	coldwireReturns.lastReplay = time.Time{}
	coldwireReturns.Unlock()
	peer.coldwireReplayReplies(identity, peer.keypairs.Current(), endpoint)
	select {
	case <-pair[0].tun.Inbound:
		t.Fatal("ciphertext replay duplicated plaintext")
	case <-time.After(50 * time.Millisecond):
	}
	pair.Send(t, Pong, nil)
}

func TestColdwireReturnCapacityAndReplayOrder(t *testing.T) {
	cache := new(coldwireReturnCache)
	now := time.Now()
	identity := [32]byte{3}
	data := make([]byte, 128)
	for i := 1; i <= coldwireReturnSlots+100; i++ {
		binary.BigEndian.PutUint32(data, uint32(i))
		cache.remember(coldwireReturnPacket{peer: identity, birth: now, index: 9, sent: now, payload: data})
	}
	if cache.count != coldwireReturnSlots || cache.bytes != coldwireReturnSlots*128 {
		t.Fatal("packet bound failed")
	}
	got := cache.selectReplies(identity, now, 9, now)
	if len(got) != coldwireReplaySlots {
		t.Fatal("replay packet bound failed")
	}
	for i, data := range got {
		if binary.BigEndian.Uint32(data) != uint32(coldwireReturnSlots+100-coldwireReplaySlots+i+1) {
			t.Fatal("replay order is not increasing")
		}
	}
	cache = new(coldwireReturnCache)
	data = make([]byte, 65536)
	for i := 0; i < 200; i++ {
		cache.remember(coldwireReturnPacket{peer: identity, birth: now, index: 9, sent: now, payload: data})
	}
	if cache.bytes > coldwireReturnBytes || cache.count != coldwireReturnBytes/len(data) {
		t.Fatal("global byte bound failed")
	}
	got = cache.selectReplies(identity, now, 9, now)
	if len(got)*len(data) != coldwireReplayBytes {
		t.Fatal("replay byte bound failed")
	}
}

func TestColdwireReturnAuthenticatedMoveAndCooldown(t *testing.T) {
	oldEnabled, oldCache := coldwireReturnEnabled, coldwireReturns
	defer func() {
		coldwireReturnEnabled, coldwireReturns = oldEnabled, oldCache
		coldwireReturnOnce = sync.Once{}
	}()
	coldwireReturnEnabled = true
	coldwireReturns = new(coldwireReturnCache)
	coldwireReturnOnce = sync.Once{}
	coldwireReturnOnce.Do(func() {})
	receiver, err := net.ListenUDP("udp4", &net.UDPAddr{IP: net.IPv4(127, 0, 0, 1)})
	if err != nil {
		t.Fatal(err)
	}
	defer receiver.Close()
	bind := conn.NewDefaultBind()
	if _, _, err = bind.Open(0); err != nil {
		t.Fatal(err)
	}
	defer bind.Close()
	endpoint, err := bind.ParseEndpoint(receiver.LocalAddr().String())
	if err != nil {
		t.Fatal(err)
	}
	peer := new(Peer)
	peer.device = new(Device)
	peer.device.net.bind = bind
	peer.device.log = NewLogger(LogLevelSilent, "")
	keypair := &Keypair{created: time.Now(), localIndex: 11}
	peer.keypairs.current = keypair
	identity := [32]byte{4}
	coldwireReturns.remember(coldwireReturnPacket{peer: identity, birth: keypair.created, index: 11, sent: time.Now(), payload: []byte("ciphertext")})
	peer.coldwireReplayReplies(identity, &Keypair{created: keypair.created, localIndex: 11}, endpoint)
	if !peer.coldwireReturnLast.IsZero() {
		t.Fatal("non-current keypair authorized replay")
	}
	peer.endpoint.disableRoaming = true
	peer.coldwireReplayReplies(identity, keypair, endpoint)
	if !peer.coldwireReturnLast.IsZero() {
		t.Fatal("disabled roaming authorized replay")
	}
	peer.endpoint.disableRoaming = false
	coldwireReplaySending.Lock()
	peer.coldwireReplayReplies(identity, keypair, endpoint)
	coldwireReplaySending.Unlock()
	if !peer.coldwireReturnLast.IsZero() {
		t.Fatal("concurrent replay was queued")
	}
	peer.coldwireReplayReplies([32]byte{99}, keypair, endpoint)
	if peer.coldwireReturnLast.IsZero() {
		t.Fatal("empty cache did not consume peer cooldown")
	}
	peer.coldwireReplayReplies(identity, keypair, endpoint)
	if peer.txBytes.Load() != 0 {
		t.Fatal("empty-cache cooldown was bypassed")
	}
	peer.coldwireReturnLast = time.Time{}
	peer.coldwireReplayReplies(identity, keypair, endpoint)
	receiver.SetReadDeadline(time.Now().Add(time.Second))
	buffer := make([]byte, 64)
	n, _, err := receiver.ReadFromUDP(buffer)
	if err != nil || string(buffer[:n]) != "ciphertext" {
		t.Fatal("authenticated move did not recover reply", err)
	}
	if peer.txBytes.Load() != 10 {
		t.Fatal("replay bytes not accounted")
	}
	peer.coldwireReplayReplies(identity, keypair, endpoint)
	receiver.SetReadDeadline(time.Now().Add(20 * time.Millisecond))
	if _, _, err = receiver.ReadFromUDP(buffer); err == nil {
		t.Fatal("peer cooldown ignored")
	}
}
