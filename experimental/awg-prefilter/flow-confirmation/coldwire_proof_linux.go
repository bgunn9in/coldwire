// SPDX-License-Identifier: MIT
// Lab-only event hook for the pinned AWG source; clients and wire packets are unchanged.
package device

import (
	"crypto/sha256"
	"encoding/binary"
	"net"
	"os"
	"strconv"
	"sync"

	"github.com/amnezia-vpn/amneziawg-go/v3/conn"
	"golang.org/x/sys/unix"
)

var coldwireProofPath = os.Getenv("COLDWIRE_LAB_PROOF_SOCKET")
var coldwireProofOnce sync.Once
var coldwireProofFD = -1

// Called only by the sequential receiver, after AEAD/replay and source-policy checks.
func (peer *Peer) coldwireProof(endpoint conn.Endpoint, counter uint64) {
	if coldwireProofPath == "" { return }
	var clock unix.Timespec
	if unix.ClockGettime(unix.CLOCK_MONOTONIC, &clock) != nil { return }
	now := clock.Nano()
	address := endpoint.DstToString()
	if address == peer.coldwireProofEndpoint && now-peer.coldwireProofLast < 250000000 { return }
	peer.coldwireProofEndpoint, peer.coldwireProofLast = address, now
	coldwireProofOnce.Do(func() {
		info, err := os.Lstat(coldwireProofPath)
		if err != nil || info.Mode()&os.ModeSocket == 0 || info.Mode().Perm() != 0600 { return }
		var stat unix.Stat_t
		if unix.Lstat(coldwireProofPath, &stat) != nil || stat.Uid != 0 { return }
		coldwireProofFD, _ = unix.Socket(unix.AF_UNIX, unix.SOCK_DGRAM|unix.SOCK_NONBLOCK|unix.SOCK_CLOEXEC, 0)
	})
	if coldwireProofFD < 0 { return }
	host, portText, err := net.SplitHostPort(address)
	if err != nil { return }
	ip := net.ParseIP(host).To4()
	port, err := strconv.Atoi(portText)
	if ip == nil || err != nil || port < 1 || port > 65535 { return }
	var event [42]byte
	copy(event[:4], "CWP1")
	binary.BigEndian.PutUint64(event[4:12], uint64(now))
	copy(event[12:16], ip)
	binary.BigEndian.PutUint16(event[16:18], uint16(port))
	peer.handshake.mutex.RLock()
	identity := sha256.Sum256(peer.handshake.remoteStatic[:])
	peer.handshake.mutex.RUnlock()
	copy(event[18:34], identity[:16])
	binary.BigEndian.PutUint64(event[34:42], counter)
	// Dropping a local notification never blocks or changes VPN packet processing.
	_ = unix.Sendto(coldwireProofFD, event[:], unix.MSG_DONTWAIT, &unix.SockaddrUnix{Name:coldwireProofPath})
}
