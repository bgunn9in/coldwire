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

const coldwireProofIntervalNS int64 = 50000000

func (peer *Peer) coldwireProofDue(address string, now int64) bool {
	if address == peer.coldwireProofEndpoint && now-peer.coldwireProofLast < coldwireProofIntervalNS {
		return false
	}
	peer.coldwireProofEndpoint, peer.coldwireProofLast = address, now
	return true
}

// Called only by the sequential receiver, after AEAD/replay and source-policy checks.
func (peer *Peer) coldwireProof(endpoint conn.Endpoint, keypair *Keypair, counter uint64) {
	if coldwireProofPath == "" {
		return
	}
	peer.keypairs.RLock()
	current := keypair != nil && keypair == peer.keypairs.current && peer.coldwireEndpointBirth == keypair.created && peer.coldwireEndpointIndex == keypair.localIndex && counter == peer.coldwireEndpointCounter
	peer.keypairs.RUnlock()
	if !current {
		return
	}
	var clock unix.Timespec
	if unix.ClockGettime(unix.CLOCK_MONOTONIC, &clock) != nil {
		return
	}
	now := clock.Nano()
	address := endpoint.DstToString()
	moved := peer.coldwireProofEndpoint != "" && peer.coldwireProofEndpoint != address
	if !peer.coldwireProofDue(address, now) {
		return
	}
	coldwireProofOnce.Do(func() {
		info, err := os.Lstat(coldwireProofPath)
		if err != nil || info.Mode()&os.ModeSocket == 0 || info.Mode().Perm() != 0600 {
			return
		}
		var stat unix.Stat_t
		if unix.Lstat(coldwireProofPath, &stat) != nil || stat.Uid != 0 {
			return
		}
		coldwireProofFD, _ = unix.Socket(unix.AF_UNIX, unix.SOCK_DGRAM|unix.SOCK_NONBLOCK|unix.SOCK_CLOEXEC, 0)
	})
	if coldwireProofFD < 0 {
		return
	}
	host, portText, err := net.SplitHostPort(address)
	if err != nil {
		return
	}
	ip := net.ParseIP(host).To4()
	port, err := strconv.Atoi(portText)
	if ip == nil || err != nil || port < 1 || port > 65535 {
		return
	}
	var event [42]byte
	copy(event[:4], "CWP1")
	binary.BigEndian.PutUint64(event[4:12], uint64(now))
	copy(event[12:16], ip)
	binary.BigEndian.PutUint16(event[16:18], uint16(port))
	peer.handshake.mutex.RLock()
	identity := sha256.Sum256(peer.handshake.remoteStatic[:])
	peer.handshake.mutex.RUnlock()
	if moved && coldwireReturnEnabled {
		peer.coldwireCommitEndpoint(endpoint, keypair, counter)
		peer.coldwireReplayReplies(identity, keypair, endpoint)
	} else if coldwireReturnEnabled {
		peer.coldwireRetryReplies(identity, keypair, endpoint)
	}
	copy(event[18:34], identity[:16])
	binary.BigEndian.PutUint64(event[34:42], counter)
	// Dropping a local notification never blocks or changes VPN packet processing.
	_ = unix.Sendto(coldwireProofFD, event[:], unix.MSG_DONTWAIT, &unix.SockaddrUnix{Name: coldwireProofPath})
}

// Only the sequential receiver updates these scalar counters; no key material is retained.
func (peer *Peer) coldwireEndpointCandidate(keypair *Keypair, counter uint64) bool {
	peer.keypairs.RLock()
	defer peer.keypairs.RUnlock()
	if keypair == nil || keypair != peer.keypairs.current {
		return false
	}
	if peer.coldwireEndpointBirth != keypair.created || peer.coldwireEndpointIndex != keypair.localIndex {
		peer.coldwireEndpointBirth, peer.coldwireEndpointIndex = keypair.created, keypair.localIndex
		peer.coldwireEndpointCounter = counter
		return true
	}
	if counter <= peer.coldwireEndpointCounter {
		return false
	}
	peer.coldwireEndpointCounter = counter
	return true
}

func (peer *Peer) coldwireCommitEndpoint(endpoint conn.Endpoint, keypair *Keypair, counter uint64) {
	peer.keypairs.RLock()
	defer peer.keypairs.RUnlock()
	if keypair == nil || keypair != peer.keypairs.current || peer.coldwireEndpointBirth != keypair.created || peer.coldwireEndpointIndex != keypair.localIndex || counter != peer.coldwireEndpointCounter {
		return
	}
	peer.SetEndpointFromPacket(endpoint)
}
