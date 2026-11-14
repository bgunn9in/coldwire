// SPDX-License-Identifier: MIT
// Optional disposable-lab recovery of ciphertext sent towards a vanished NAT mapping.
package device

import (
	"crypto/sha256"
	"os"
	"sync"
	"time"

	"github.com/amnezia-vpn/amneziawg-go/v3/conn"
)

const (
	coldwireReturnSlots = 8192
	coldwireReturnBytes = 8 << 20
	coldwireReturnAge   = 500 * time.Millisecond
	coldwireReplaySlots = 4096
	coldwireReplayBytes = 2 << 20
)

var coldwireReturnEnabled = os.Getenv("COLDWIRE_LAB_RETURN_REPLAY") == "1" && coldwireProofPath != ""
var coldwireReturnOnce sync.Once
var coldwireReturns *coldwireReturnCache
var coldwireReplaySending sync.Mutex

type coldwireReturnPacket struct {
	peer    [32]byte
	birth   time.Time
	index   uint32
	sent    time.Time
	payload []byte
}

type coldwireReturnCache struct {
	sync.Mutex
	packets            [coldwireReturnSlots]coldwireReturnPacket
	head, count, bytes int
	lastReplay         time.Time
}

func (cache *coldwireReturnCache) discard() {
	cache.bytes -= len(cache.packets[cache.head].payload)
	cache.packets[cache.head] = coldwireReturnPacket{}
	cache.head = (cache.head + 1) % coldwireReturnSlots
	cache.count--
}

func (cache *coldwireReturnCache) prune(now time.Time) {
	for cache.count > 0 && now.Sub(cache.packets[cache.head].sent) >= coldwireReturnAge {
		cache.discard()
	}
}

func (cache *coldwireReturnCache) remember(packet coldwireReturnPacket) {
	cache.Lock()
	defer cache.Unlock()
	cache.prune(packet.sent)
	if len(packet.payload) > coldwireReturnBytes {
		return
	}
	for cache.count == coldwireReturnSlots || cache.bytes+len(packet.payload) > coldwireReturnBytes {
		cache.discard()
	}
	data := make([]byte, len(packet.payload))
	copy(data, packet.payload)
	packet.payload = data
	cache.packets[(cache.head+cache.count)%coldwireReturnSlots] = packet
	cache.count++
	cache.bytes += len(data)
}

func (cache *coldwireReturnCache) selectReplies(peer [32]byte, birth time.Time, index uint32, now time.Time) [][]byte {
	cache.Lock()
	defer cache.Unlock()
	cache.prune(now)
	if !cache.lastReplay.IsZero() && now.Sub(cache.lastReplay) < 250*time.Millisecond {
		return nil
	}
	var buffers [][]byte
	size := 0
	for i := cache.count - 1; i >= 0 && len(buffers) < coldwireReplaySlots; i-- {
		packet := &cache.packets[(cache.head+i)%coldwireReturnSlots]
		if packet.peer != peer || packet.birth != birth || packet.index != index || now.Sub(packet.sent) >= coldwireReturnAge {
			continue
		}
		if size+len(packet.payload) > coldwireReplayBytes {
			break
		}
		data := make([]byte, len(packet.payload))
		copy(data, packet.payload)
		buffers = append(buffers, data)
		size += len(data)
	}
	for i, j := 0, len(buffers)-1; i < j; i, j = i+1, j-1 {
		buffers[i], buffers[j] = buffers[j], buffers[i]
	}
	if len(buffers) > 0 {
		cache.lastReplay = now
	}
	return buffers
}

func coldwireReturnStorage() *coldwireReturnCache {
	coldwireReturnOnce.Do(func() {
		coldwireReturns = new(coldwireReturnCache)
		go func() {
			for now := range time.Tick(100 * time.Millisecond) {
				coldwireReturns.Lock()
				coldwireReturns.prune(now)
				coldwireReturns.Unlock()
			}
		}()
	})
	return coldwireReturns
}

func (peer *Peer) coldwireRememberReply(payload []byte, keypair *Keypair) {
	if !coldwireReturnEnabled || keypair == nil {
		return
	}
	peer.handshake.mutex.RLock()
	identity := sha256.Sum256(peer.handshake.remoteStatic[:])
	peer.handshake.mutex.RUnlock()
	coldwireReturnStorage().remember(coldwireReturnPacket{peer: identity, birth: keypair.created, index: keypair.localIndex, sent: time.Now(), payload: payload})
}

// Called only for a changed, freshly authenticated endpoint after source-policy checking.
func (peer *Peer) coldwireReplayReplies(identity [32]byte, keypair *Keypair, endpoint conn.Endpoint) {
	if !coldwireReturnEnabled || keypair == nil || peer.keypairs.Current() != keypair {
		return
	}
	if !coldwireReplaySending.TryLock() {
		return
	}
	defer coldwireReplaySending.Unlock()
	peer.endpoint.Lock()
	disabled := peer.endpoint.disableRoaming
	peer.endpoint.Unlock()
	now := time.Now()
	if disabled || (!peer.coldwireReturnLast.IsZero() && now.Sub(peer.coldwireReturnLast) < time.Second) {
		return
	}
	peer.coldwireReturnLast = now
	buffers := coldwireReturnStorage().selectReplies(identity, keypair.created, keypair.localIndex, now)
	if len(buffers) == 0 {
		return
	}
	peer.device.net.RLock()
	defer peer.device.net.RUnlock()
	if peer.device.isClosed() {
		return
	}
	batch := peer.device.net.bind.BatchSize()
	for offset := 0; offset < len(buffers); offset += batch {
		end := min(offset+batch, len(buffers))
		if err := peer.device.net.bind.Send(buffers[offset:end], endpoint); err != nil {
			peer.device.log.Errorf("%v - Lab return replay stopped: %v", peer, err)
			return
		}
		for _, packet := range buffers[offset:end] {
			peer.txBytes.Add(uint64(len(packet)))
		}
	}
}
