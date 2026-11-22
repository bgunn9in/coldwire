package main

import (
	"context"
	"crypto/sha256"
	"encoding/binary"
	"errors"
	"net"
	"net/netip"
	"os"
	"os/exec"
	"path/filepath"
	"strconv"
	"strings"
	"testing"
	"time"
)

var testKeys = keyConfig{CookieKey: strings.Repeat("ab", 32), Devices: []string{strings.Repeat("12", 32)}}

func TestAdmission(t *testing.T) {
	var grants []netip.Addr
	grant := func(source netip.Addr, admin bool) error {
		if admin {
			t.Fatal("a VPN key granted SSH access")
		}
		grants = append(grants, source)
		return nil
	}
	a, err := newAdmission(testKeys, grant)
	if err != nil {
		t.Fatal(err)
	}
	accepted := netip.MustParseAddr("192.0.2.25")
	other := netip.MustParseAddr("192.0.2.26")
	now := time.Unix(1770000000, 0)
	device, _ := key(testKeys.Devices[0])
	body := make([]byte, bodySize)
	copy(body, "CWQ1")
	id := sha256.Sum256(device[:])
	copy(body[4:12], id[:8])
	binary.BigEndian.PutUint64(body[12:20], uint64(now.Unix()))
	body[20] = 9
	discover := sign(body, device)
	for _, junk := range [][]byte{discover[:12], append(discover, 0), sign(body, [32]byte{99})} {
		if reply, err := a.handle(junk, accepted, now); reply != nil || err != nil {
			t.Fatal("invalid discovery got a reply")
		}
	}
	challenge, err := a.handle(discover, accepted, now)
	if err != nil || len(challenge) != frameSize || string(challenge[:4]) != "CWC1" {
		t.Fatal("authenticated discovery failed")
	}
	copy(challenge, "CWA1")
	authorize := sign(challenge[:bodySize], device)
	if reply, _ := a.handle(authorize, other, now); reply != nil {
		t.Fatal("allowed wrong source address")
	}
	if reply, _ := a.handle(authorize, accepted, now.Add(21*time.Second)); reply != nil {
		t.Fatal("allowed an expired challenge")
	}
	if reply, err := a.handle(authorize, accepted, now); len(reply) != frameSize || string(reply[:4]) != "CWO1" || err != nil {
		t.Fatal("valid authorization failed")
	}
	if reply, _ := a.handle(authorize, accepted, now); reply != nil {
		t.Fatal("duplicate authorization succeeded")
	}
	restarted, err := newAdmission(testKeys, grant)
	if err != nil {
		t.Fatal(err)
	}
	if reply, _ := restarted.handle(authorize, accepted, now); reply != nil || len(grants) != 1 || grants[0] != accepted {
		t.Fatal("old cookie authorized after server restart")
	}
	a.grant = func(netip.Addr, bool) error { return errors.New("fixture nft failure") }
	body[20]++
	challenge, err = a.handle(sign(body, device), accepted, now)
	if err != nil || len(challenge) != frameSize {
		t.Fatal("second discovery failed")
	}
	copy(challenge, "CWA1")
	if reply, err := a.handle(sign(challenge[:bodySize], device), accepted, now); reply != nil || err == nil {
		t.Fatal("confirmed a failed nft update")
	}
}

func TestExternalClients(t *testing.T) {
	for _, client := range []struct {
		name, command string
		args          func(string, string) []string
	}{
		{"qt", os.Getenv("CW_SPA_QT_TEST"), func(port, key string) []string { return []string{"127.0.0.1", port, key} }},
		{"android-jvm", os.Getenv("CW_SPA_JAVA"), func(port, key string) []string {
			return []string{"-cp", os.Getenv("CW_SPA_KOTLIN_CP"), "org.amnezia.vpn.AndroidSpaSmokeKt", "127.0.0.1", port, key}
		}},
		{"python-admin", os.Getenv("CW_SPA_PYTHON"), func(port, key string) []string {
			return []string{"../spa_access.py", "request", "127.0.0.1", key, "--port", port}
		}},
	} {
		t.Run(client.name, func(t *testing.T) {
			if client.command == "" {
				t.Skip("external client is not configured")
			}
			grants := make(chan netip.Addr, 10)
			access, err := newAdmission(testKeys, func(addr netip.Addr, admin bool) error {
				if admin {
					return errors.New("VPN key granted admin access")
				}
				grants <- addr
				return nil
			})
			if err != nil {
				t.Fatal(err)
			}
			conn, err := net.ListenUDP("udp4", &net.UDPAddr{IP: net.IPv4(127, 0, 0, 1)})
			if err != nil {
				t.Fatal(err)
			}
			t.Cleanup(func() { conn.Close() })
			done := make(chan error, 1)
			go func() { done <- access.serve(conn) }()
			port := strconv.Itoa(conn.LocalAddr().(*net.UDPAddr).Port)
			keyfile := filepath.Join(t.TempDir(), "device.key")
			for _, valid := range []bool{true, false} {
				secret := testKeys.Devices[0]
				if !valid {
					secret = strings.Repeat("fd", 32)
				}
				if err := os.WriteFile(keyfile, []byte(secret), 0o600); err != nil {
					t.Fatal(err)
				}
				ctx, cancel := context.WithTimeout(context.Background(), 8*time.Second)
				out, err := exec.CommandContext(ctx, client.command, client.args(port, keyfile)...).CombinedOutput()
				timedOut := ctx.Err() != nil
				cancel()
				var status *exec.ExitError
				expectedRejection := 2
				if client.name == "python-admin" {
					expectedRejection = 1
				}
				if timedOut || (valid && err != nil) || (!valid && (!errors.As(err, &status) || status.ExitCode() != expectedRejection)) {
					select {
					case serverError := <-done:
						t.Fatalf("server stopped: %v", serverError)
					default:
					}
					t.Fatalf("valid=%v: %v: %s", valid, err, out)
				}
			}
			if len(grants) != 1 || <-grants != netip.MustParseAddr("127.0.0.1") {
				t.Fatal("exactly one grant was expected")
			}
		})
	}
}

func TestAdminScope(t *testing.T) {
	adminKey := strings.Repeat("c7", 32)
	config := testKeys
	config.Admins = []string{adminKey}
	var adminGranted bool
	a, err := newAdmission(config, func(_ netip.Addr, admin bool) error {
		adminGranted = admin
		return nil
	})
	if err != nil {
		t.Fatal(err)
	}
	secret, _ := key(adminKey)
	id := sha256.Sum256(secret[:])
	now := time.Unix(1770000000, 0)
	source := netip.MustParseAddr("192.0.2.25")
	var body [bodySize]byte
	copy(body[:4], "CWQ1")
	copy(body[4:12], id[:8])
	binary.BigEndian.PutUint64(body[12:20], uint64(now.Unix()))
	challenge, err := a.handle(sign(body[:], secret), source, now)
	if err != nil || len(challenge) != frameSize {
		t.Fatal("admin discovery failed")
	}
	copy(challenge, "CWA1")
	reply, err := a.handle(sign(challenge[:bodySize], secret), source, now)
	if err != nil || !adminGranted || len(reply) != frameSize {
		t.Fatal("admin key did not grant SSH access")
	}
	config.Admins = config.Devices
	if _, err := newAdmission(config, nftGrant); err == nil {
		t.Fatal("accepted duplicate key across roles")
	}
}
