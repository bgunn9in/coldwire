package main

import (
	"context"
	"crypto/hmac"
	"crypto/rand"
	"crypto/sha256"
	"encoding/binary"
	"encoding/hex"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"log"
	"net"
	"net/netip"
	"os"
	"os/exec"
	"strings"
	"time"
)

const (
	bodySize  = 72
	frameSize = bodySize + sha256.Size
	maxReplay = 4096
	nftSet    = "inet coldwire_access spa_clients"
	adminSet  = "inet coldwire_lockdown spa_admins"
)

type keyConfig struct {
	CookieKey string   `json:"cookie_key"`
	Devices   []string `json:"devices"`
	Admins    []string `json:"admins,omitempty"`
}

type deviceKey struct {
	secret [32]byte
	admin  bool
}

type admission struct {
	keys      map[[8]byte]deviceKey
	cookieKey [32]byte
	seen      map[[24]byte]time.Time
	nextPrune time.Time
	grant     func(netip.Addr, bool) error
}

func key(text string) ([32]byte, error) {
	value, err := hex.DecodeString(text)
	if err != nil || len(value) != 32 {
		return [32]byte{}, errors.New("SPA keys must be 32 bytes in hexadecimal")
	}
	return [32]byte(value), nil
}

func mac(key, data []byte) [32]byte {
	signer := hmac.New(sha256.New, key)
	signer.Write(data)
	return [32]byte(signer.Sum(nil))
}

func newAdmission(config keyConfig, grant func(netip.Addr, bool) error) (*admission, error) {
	secret, err := key(config.CookieKey)
	if err != nil {
		return nil, err
	}
	count := len(config.Devices) + len(config.Admins)
	if count == 0 || count > maxReplay {
		return nil, errors.New("expected between 1 and 4096 SPA keys")
	}
	var epoch [32]byte
	if _, err := rand.Read(epoch[:]); err != nil {
		return nil, err
	}
	access := &admission{
		keys: make(map[[8]byte]deviceKey, count), cookieKey: mac(secret[:], epoch[:]),
		seen: make(map[[24]byte]time.Time), grant: grant,
	}
	for scope, values := range [][]string{config.Devices, config.Admins} {
		for _, value := range values {
			device, err := key(value)
			if err != nil {
				return nil, err
			}
			digest := sha256.Sum256(device[:])
			id := [8]byte(digest[:8])
			if _, exists := access.keys[id]; exists {
				return nil, errors.New("duplicate SPA key ID")
			}
			access.keys[id] = deviceKey{device, scope == 1}
		}
	}
	return access, nil
}

func sign(body []byte, key [32]byte) []byte {
	var frame [frameSize]byte
	copy(frame[:], body)
	tag := mac(key[:], body)
	copy(frame[bodySize:], tag[:])
	return frame[:]
}

func (a *admission) handle(frame []byte, source netip.Addr, now time.Time) ([]byte, error) {
	if len(frame) != frameSize || !source.Is4() {
		return nil, nil
	}
	body := frame[:bodySize]
	device, ok := a.keys[[8]byte(body[4:12])]
	if !ok {
		return nil, nil
	}
	tag := mac(device.secret[:], body)
	if !hmac.Equal(tag[:], frame[bodySize:]) {
		return nil, nil
	}
	stamp := binary.BigEndian.Uint64(body[12:20])
	unix := uint64(now.Unix())
	observed := source.As4()
	if string(body[:4]) == "CWQ1" && [36]byte(body[36:]) == [36]byte{} && stamp <= unix+60 && stamp+60 >= unix {
		challenge := [bodySize]byte(body)
		copy(challenge[:4], "CWC1")
		binary.BigEndian.PutUint64(challenge[12:20], unix)
		copy(challenge[36:40], observed[:])
		cookie := mac(a.cookieKey[:], challenge[:])
		copy(challenge[40:], cookie[:])
		return sign(challenge[:], device.secret), nil
	}
	if string(body[:4]) != "CWA1" || [4]byte(body[36:40]) != observed || stamp > unix || unix-stamp > 20 {
		return nil, nil
	}
	challenge := [bodySize]byte(body)
	copy(challenge[:4], "CWC1")
	clear(challenge[40:])
	cookie := mac(a.cookieKey[:], challenge[:])
	if !hmac.Equal(cookie[:], body[40:]) {
		return nil, nil
	}
	if !now.Before(a.nextPrune) {
		for id, until := range a.seen {
			if !now.Before(until) {
				delete(a.seen, id)
			}
		}
		a.nextPrune = now.Add(20 * time.Second)
	}
	var authorization [24]byte
	copy(authorization[:8], body[4:12])
	copy(authorization[8:], body[20:36])
	if _, duplicate := a.seen[authorization]; duplicate || len(a.seen) >= maxReplay {
		return nil, nil
	}
	a.seen[authorization] = now.Add(120 * time.Second)
	if err := a.grant(source, device.admin); err != nil {
		return nil, err
	}
	confirmation := [bodySize]byte(body)
	copy(confirmation[:4], "CWO1")
	return sign(confirmation[:], device.secret), nil
}

func nftGrant(address netip.Addr, admin bool) error {
	ctx, cancel := context.WithTimeout(context.Background(), 3*time.Second)
	defer cancel()
	set := nftSet
	if admin {
		set = adminSet
	}
	add := fmt.Sprintf("add element %s { %s timeout 120s }\n", set, address)
	args := append([]string{"get", "element"}, strings.Fields(set)...)
	args = append(args, "{", address.String(), "}")
	if exec.CommandContext(ctx, "nft", args...).Run() == nil {
		if runNft(ctx, fmt.Sprintf("delete element %s { %s }\n", set, address)+add) == nil {
			return nil
		}
	}
	return runNft(ctx, add)
}

func runNft(ctx context.Context, script string) error {
	cmd := exec.CommandContext(ctx, "nft", "-f", "-")
	cmd.Stdin = strings.NewReader(script)
	return cmd.Run()
}

func readKeys(path string) (keyConfig, error) {
	var config keyConfig
	file, err := os.Open(path)
	if err != nil {
		return config, err
	}
	defer file.Close()
	info, err := file.Stat()
	if err != nil {
		return config, err
	}
	if !info.Mode().IsRegular() || info.Mode().Perm()&0o077 != 0 || info.Size() > 300000 {
		return config, errors.New("expected a private regular SPA keys file")
	}
	decoder := json.NewDecoder(io.LimitReader(file, 300001))
	decoder.DisallowUnknownFields()
	if err := decoder.Decode(&config); err != nil {
		return config, errors.New("invalid SPA keys JSON")
	}
	if decoder.Decode(new(json.RawMessage)) != io.EOF {
		return config, errors.New("invalid trailing SPA keys data")
	}
	return config, nil
}

func (a *admission) serve(conn *net.UDPConn) error {
	var packet [65536]byte
	for {
		n, peer, err := conn.ReadFromUDPAddrPort(packet[:])
		if err != nil {
			return err
		}
		reply, err := a.handle(packet[:n], peer.Addr().Unmap(), time.Now())
		if err != nil {
			log.Print("could not update SPA allowlist")
			continue
		}
		if len(reply) != 0 {
			if _, err := conn.WriteToUDPAddrPort(reply, peer); err != nil {
				log.Print("could not send SPA reply")
			}
		}
	}
}

func run() error {
	bind := flag.String("bind", "", "local IPv4 address")
	port := flag.Uint("port", 62201, "SPA UDP port")
	path := flag.String("keys", "/etc/coldwire-access/spa-keys.json", "device and cookie keys file")
	check := flag.Bool("check-keys", false, "validate the key file and exit")
	flag.Parse()
	config, err := readKeys(*path)
	if err != nil {
		return err
	}
	access, err := newAdmission(config, nftGrant)
	if err != nil || *check {
		return err
	}
	address, err := netip.ParseAddr(*bind)
	if err != nil || !address.Is4() || *port == 0 || *port > 65535 || flag.NArg() != 0 {
		return errors.New("expected a local IPv4 --bind and a valid UDP --port")
	}
	conn, err := net.ListenUDP("udp4", net.UDPAddrFromAddrPort(netip.AddrPortFrom(address, uint16(*port))))
	if err != nil {
		return err
	}
	defer conn.Close()
	return access.serve(conn)
}

func main() {
	if err := run(); err != nil {
		log.Fatal(err)
	}
}
