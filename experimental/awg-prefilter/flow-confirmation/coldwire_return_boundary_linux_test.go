// SPDX-License-Identifier: MIT
package device

import (
	"encoding/binary"
	"testing"
	"time"

	"github.com/amnezia-vpn/amneziawg-go/v3/replay"
)

func TestColdwireReturnExactAgeBoundary(t *testing.T) {
	now := time.Now()
	for _, age := range []time.Duration{coldwireReturnAge - time.Nanosecond, coldwireReturnAge, coldwireReturnAge + time.Nanosecond} {
		cache := new(coldwireReturnCache)
		cache.remember(coldwireReturnPacket{peer: [32]byte{1}, birth: now, index: 1, sent: now, payload: []byte{1}})
		got := cache.selectReplies([32]byte{1}, now, 1, now.Add(age))
		want := 0
		if age < coldwireReturnAge {
			want = 1
		}
		if len(got) != want {
			t.Fatalf("age %v: got %d replies, want %d", age, len(got), want)
		}
	}
}

func TestColdwireReturnSharedCacheCanEvictAnotherPeer(t *testing.T) {
	cache := new(coldwireReturnCache)
	now := time.Now()
	cache.remember(coldwireReturnPacket{peer: [32]byte{1}, birth: now, index: 1, sent: now, payload: []byte{1}})
	for i := 0; i < coldwireReturnSlots; i++ {
		cache.remember(coldwireReturnPacket{peer: [32]byte{2}, birth: now, index: 2, sent: now, payload: []byte{2}})
	}
	if got := cache.selectReplies([32]byte{1}, now, 1, now.Add(time.Millisecond)); len(got) != 0 {
		t.Fatal("the globally evicted peer unexpectedly retained a reply")
	}
	if cache.count != coldwireReturnSlots || cache.bytes != coldwireReturnSlots {
		t.Fatal("shared packet or byte bound changed")
	}
}

func TestColdwireReturnByteBudgetSelectsNewestSuffix(t *testing.T) {
	cache := new(coldwireReturnCache)
	now := time.Now()
	const size = 1400
	const count = 2000
	for i := 1; i <= count; i++ {
		payload := make([]byte, size)
		binary.BigEndian.PutUint32(payload, uint32(i))
		cache.remember(coldwireReturnPacket{peer: [32]byte{1}, birth: now, index: 1, sent: now, payload: payload})
	}
	got := cache.selectReplies([32]byte{1}, now, 1, now.Add(time.Millisecond))
	want := coldwireReplayBytes / size
	if len(got) != want || cache.count != count {
		t.Fatalf("selected %d of %d packets, want %d", len(got), cache.count, want)
	}
	for i, payload := range got {
		if binary.BigEndian.Uint32(payload) != uint32(count-want+i+1) {
			t.Fatal("byte-limited recovery did not preserve the newest increasing suffix")
		}
	}
}

func TestColdwireReturnClientReplayWindowBoundary(t *testing.T) {
	const window = 8128 // Pinned upstream replay window: (128 - 1) * 64.
	const limit = ^uint64(0) - 8192
	var filter replay.Filter
	if !filter.ValidateCounter(1+window, limit) || !filter.ValidateCounter(1, limit) {
		t.Fatal("an unseen counter at the replay-window edge was rejected")
	}
	if filter.ValidateCounter(1, limit) {
		t.Fatal("the recovered counter produced duplicate acceptance")
	}
	filter.Reset()
	if !filter.ValidateCounter(2+window, limit) || filter.ValidateCounter(1, limit) {
		t.Fatal("an unseen counter behind the replay window was accepted")
	}
}
