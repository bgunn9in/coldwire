// SPDX-License-Identifier: MIT
package device

import (
	"testing"

	"github.com/amnezia-vpn/amneziawg-go/v3/replay"
)

func TestColdwireReceiverWindowPreservesDelayedUnseen(t *testing.T) {
	const limit = uint64(100000)
	var server coldwireReplayFilter
	var client replay.Filter
	if !server.ValidateCounter(20000, limit) || !client.ValidateCounter(20000, limit) {
		t.Fatal("initial counter rejected")
	}
	if !server.ValidateCounter(8000, limit) || client.ValidateCounter(8000, limit) {
		t.Fatal("server and unchanged client windows disagree with their bounds")
	}
	if server.ValidateCounter(8000, limit) {
		t.Fatal("duplicate accepted")
	}
	if !server.ValidateCounter(3680, limit) || server.ValidateCounter(3679, limit) {
		t.Fatal("16320 boundary")
	}
	if server.ValidateCounter(limit, limit) || server.last != 20000 {
		t.Fatal("counter limit altered state")
	}
	server.Reset()
	if !server.ValidateCounter(8000, limit) || server.ValidateCounter(8000, limit) {
		t.Fatal("reset or duplicate rejection")
	}
}
