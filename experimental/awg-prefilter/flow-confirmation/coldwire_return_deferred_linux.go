// SPDX-License-Identifier: MIT
package device

import (
	"time"

	"github.com/amnezia-vpn/amneziawg-go/v3/conn"
)

const (
	coldwirePendingPeers   = 16
	coldwirePendingAge     = 1100 * time.Millisecond
	coldwirePendingBytes   = 16 << 20
	coldwirePendingPackets = coldwireReplaySlots
)

// The bounded peer reference supplies the current key/endpoint without retaining a keypair.
type coldwireReturnPending struct {
	peer    *Peer
	birth   time.Time
	index   uint32
	address string
	due     time.Time
	expires time.Time
	buffers [][]byte
	through uint64
	armed   bool
}

// Reuse the selected ciphertext so a second move cannot erase the first recovery window.
func (cache *coldwireReturnCache) holdReplies(identity [32]byte, birth time.Time, index uint32, address string, now time.Time, through uint64, buffers [][]byte) {
	cache.Lock()
	defer cache.Unlock()
	cache.prunePending(now)
	if _, ok := cache.pending[identity]; ok || len(buffers) == 0 || len(cache.pending) >= coldwirePendingPeers || cache.pendingPackets+len(buffers) > coldwirePendingPackets {
		return
	}
	size := 0
	for _, buffer := range buffers {
		size += len(buffer)
	}
	if cache.pendingBytes+size > coldwirePendingBytes {
		return
	}
	if cache.pending == nil {
		cache.pending = make(map[[32]byte]coldwireReturnPending)
	}
	cache.pending[identity] = coldwireReturnPending{birth: birth, index: index, address: address, due: now.Add(coldwirePeerReplayInterval), expires: now.Add(coldwirePendingAge), buffers: append([][]byte(nil), buffers...), through: through}
	cache.pendingBytes += size
	cache.pendingPackets += len(buffers)
}

func (cache *coldwireReturnCache) dropPending(identity [32]byte) {
	value, ok := cache.pending[identity]
	if !ok {
		return
	}
	for _, buffer := range value.buffers {
		cache.pendingBytes -= len(buffer)
	}
	cache.pendingPackets -= len(value.buffers)
	delete(cache.pending, identity)
}

func (cache *coldwireReturnCache) prunePending(now time.Time) {
	for identity, value := range cache.pending {
		if !now.Before(value.expires) {
			cache.dropPending(identity)
		}
	}
}

func (cache *coldwireReturnCache) cancelPending(identity [32]byte) {
	cache.Lock()
	defer cache.Unlock()
	cache.dropPending(identity)
}

func (cache *coldwireReturnCache) retargetPending(identity [32]byte, birth time.Time, index uint32, address string, now time.Time) bool {
	cache.Lock()
	defer cache.Unlock()
	cache.prunePending(now)
	value, ok := cache.pending[identity]
	if !ok {
		return false
	}
	if value.birth != birth || value.index != index {
		cache.dropPending(identity)
		return false
	}
	value.address = address
	value.armed = true
	cache.prune(now)
	for i := 0; i < cache.count && cache.pendingPackets < coldwirePendingPackets; i++ {
		packet := &cache.packets[(cache.head+i)%coldwireReturnSlots]
		if packet.serial <= value.through || packet.peer != identity || packet.birth != birth || packet.index != index || now.Sub(packet.sent) >= coldwireReturnAge {
			continue
		}
		if cache.pendingBytes+len(packet.payload) > coldwirePendingBytes {
			break
		}
		value.buffers = append(value.buffers, append([]byte(nil), packet.payload...))
		value.through = packet.serial
		cache.pendingBytes += len(packet.payload)
		cache.pendingPackets++
	}
	cache.pending[identity] = value
	return true
}

func (cache *coldwireReturnCache) deferReplies(identity [32]byte, birth time.Time, index uint32, address string, now, due time.Time) {
	cache.Lock()
	defer cache.Unlock()
	cache.prunePending(now)
	if _, ok := cache.pending[identity]; ok || len(cache.pending) >= coldwirePendingPeers {
		return
	}
	cache.prune(now)
	value := coldwireReturnPending{birth: birth, index: index, address: address, due: due, expires: now.Add(coldwirePendingAge), through: cache.serial, armed: true}
	if next := cache.lastReplay.Add(250 * time.Millisecond); next.After(value.due) {
		value.due = next
	}
	size := 0
	for i := cache.count - 1; i >= 0 && cache.pendingPackets+len(value.buffers) < coldwirePendingPackets; i-- {
		packet := &cache.packets[(cache.head+i)%coldwireReturnSlots]
		if packet.peer != identity || packet.birth != birth || packet.index != index || now.Sub(packet.sent) >= coldwireReturnAge {
			continue
		}
		if cache.pendingBytes+size+len(packet.payload) > coldwirePendingBytes {
			break
		}
		value.buffers = append(value.buffers, append([]byte(nil), packet.payload...))
		size += len(packet.payload)
	}
	if len(value.buffers) == 0 {
		return
	}
	for i, j := 0, len(value.buffers)-1; i < j; i, j = i+1, j-1 {
		value.buffers[i], value.buffers[j] = value.buffers[j], value.buffers[i]
	}
	if cache.pending == nil {
		cache.pending = make(map[[32]byte]coldwireReturnPending)
	}
	cache.pending[identity] = value
	cache.pendingBytes += size
	cache.pendingPackets += len(value.buffers)
}

func (cache *coldwireReturnCache) takePending(identity [32]byte, birth time.Time, index uint32, address string, now time.Time) [][]byte {
	cache.Lock()
	defer cache.Unlock()
	cache.prunePending(now)
	value, ok := cache.pending[identity]
	if !ok {
		return nil
	}
	if value.birth != birth || value.index != index || value.address != address {
		cache.dropPending(identity)
		return nil
	}
	if !value.armed || now.Before(value.due) || (!cache.lastReplay.IsZero() && now.Sub(cache.lastReplay) < 250*time.Millisecond) {
		return nil
	}
	// The authenticated destination can disappear before this attempt arrives.
	value.armed = false
	value.due = now.Add(coldwirePeerReplayInterval)
	cache.pending[identity] = value
	cache.lastReplay = now
	return value.buffers
}

func (peer *Peer) coldwireDeferReplies(identity [32]byte, keypair *Keypair, endpoint conn.Endpoint, now time.Time) {
	if !peer.isRunning.Load() {
		return
	}
	due := peer.coldwireReturnLast.Add(coldwirePeerReplayInterval)
	if due.Before(now) {
		due = now
	}
	coldwireReturnStorage().deferReplies(identity, keypair.created, keypair.localIndex, endpoint.DstToString(), now, due)
	coldwireReturnStorage().watchPending(identity, peer)
}

// Called only by the sequential receiver with fresh, source-checked current-key transport.
func (peer *Peer) coldwireRetryReplies(identity [32]byte, keypair *Keypair, endpoint conn.Endpoint) {
	peer.coldwireReturnMu.Lock()
	defer peer.coldwireReturnMu.Unlock()
	peer.coldwireRetryRepliesLocked(identity, keypair, endpoint)
}

func (peer *Peer) coldwireRetryRepliesLocked(identity [32]byte, keypair *Keypair, endpoint conn.Endpoint) {
	if !coldwireReturnEnabled || peer.device == nil || keypair == nil {
		return
	}
	cache := coldwireReturnStorage()
	if !peer.isRunning.Load() || peer.device.isClosed() || peer.keypairs.Current() != keypair {
		cache.cancelPending(identity)
		return
	}
	peer.endpoint.Lock()
	current := !peer.endpoint.disableRoaming && peer.endpoint.val != nil && peer.endpoint.val.DstToString() == endpoint.DstToString()
	peer.endpoint.Unlock()
	if !current {
		cache.cancelPending(identity)
		return
	}
	now := time.Now()
	if (!peer.coldwireReturnLast.IsZero() && now.Sub(peer.coldwireReturnLast) < coldwirePeerReplayInterval) || !coldwireReplaySending.TryLock() {
		return
	}
	defer coldwireReplaySending.Unlock()
	buffers := cache.takePending(identity, keypair.created, keypair.localIndex, endpoint.DstToString(), now)
	if len(buffers) == 0 {
		return
	}
	peer.coldwireReturnLast = now
	peer.device.log.Verbosef("%v - Lab return attempt kind=deferred packets=%d target=%s", peer, len(buffers), endpoint.DstToString())
	peer.coldwireSendReplies(keypair, endpoint, buffers)
}

func (cache *coldwireReturnCache) watchPending(identity [32]byte, peer *Peer) {
	cache.Lock()
	defer cache.Unlock()
	if value, ok := cache.pending[identity]; ok {
		value.peer = peer
		cache.pending[identity] = value
	}
}

// Reuse the existing expiry loop so a quiet client cannot strand an armed retry.
func (cache *coldwireReturnCache) maintain(now time.Time) {
	var ready [coldwirePendingPeers]struct {
		identity [32]byte
		peer     *Peer
	}
	n := 0
	cache.Lock()
	cache.prune(now)
	cache.prunePending(now)
	for identity, value := range cache.pending {
		if value.peer != nil && value.armed && !now.Before(value.due) {
			ready[n].identity, ready[n].peer = identity, value.peer
			n++
		}
	}
	cache.Unlock()
	for _, item := range ready[:n] {
		peer := item.peer
		if !peer.coldwireReturnMu.TryLock() {
			continue
		}
		keypair := peer.keypairs.Current()
		peer.endpoint.Lock()
		endpoint := peer.endpoint.val
		peer.endpoint.Unlock()
		if keypair != nil && endpoint != nil {
			cache.Lock()
			value, ok := cache.pending[item.identity]
			current := ok && value.peer == peer && value.birth == keypair.created && value.index == keypair.localIndex && value.address == endpoint.DstToString()
			cache.Unlock()
			if current {
				peer.coldwireRetryRepliesLocked(item.identity, keypair, endpoint)
			}
		}
		peer.coldwireReturnMu.Unlock()
	}
}
