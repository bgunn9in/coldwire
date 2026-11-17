// SPDX-License-Identifier: MIT
// Run inside the pinned amneziawg-go module; output contains only public test keys.
package main

import (
	"encoding/base64"
	"encoding/binary"
	"encoding/hex"
	"encoding/json"
	"fmt"
	"golang.org/x/crypto/blake2s"
	"golang.org/x/crypto/chacha20"
)

type Config struct {
	Name     string      `json:"name"`
	S        []int       `json:"padding"`
	H        [][2]uint32 `json:"headers"`
	Trailers bool        `json:"trailers"`
}

func main() {
	configs := []Config{
		{"mixed", []int{32, 48, 64, 80}, [][2]uint32{{100100, 100199}, {200100, 200199}, {300100, 300199}, {400100, 400199}}, true},
		{"equal", []int{96, 96, 96, 96}, [][2]uint32{{0, 0}, {0x80000000, 0x8000000f}, {123456, 123499}, {0xfffffff0, 0xffffffff}}, false},
		{"large", []int{1024, 512, 256, 128}, [][2]uint32{{70000, 70009}, {80000, 80009}, {90000, 90009}, {100000, 100009}}, true},
	}
	key := make([]byte, 32)
	pub := make([]byte, 32)
	for i := range key {
		key[i] = byte(i)
		pub[i] = byte(63 - i)
	}
	material := append([]byte("mac1----"), pub...)
	mk := blake2s.Sum256(material)
	cases := []map[string]any{}
	for _, c := range configs {
		params := map[string]string{}
		for i := 0; i < 4; i++ {
			params[fmt.Sprintf("S%d", i+1)] = fmt.Sprint(c.S[i])
			params[fmt.Sprintf("H%d", i+1)] = fmt.Sprint(c.H[i][0])
			if c.H[i][0] != c.H[i][1] {
				params[fmt.Sprintf("H%d", i+1)] = fmt.Sprintf("%d-%d", c.H[i][0], c.H[i][1])
			}
		}
		params["RandomTrailers"] = "0"
		if c.Trailers {
			params["RandomTrailers"] = "1"
		}
		packets := []map[string]any{}
		for i, size := range []int{148, 92, 64, 32} {
			for _, h := range []uint32{c.H[i][0], c.H[i][1]} {
				msg := make([]byte, size)
				binary.LittleEndian.PutUint32(msg, h)
				for n := 4; n < size-32; n++ {
					msg[n] = byte(n * 17)
				}
				if i < 2 {
					m, _ := blake2s.New128(mk[:])
					m.Write(msg[:size-32])
					copy(msg[size-32:], m.Sum(nil))
				}
				padding := make([]byte, c.S[i])
				for n := range padding {
					padding[n] = byte(n*13 + i)
				}
				cipher, _ := chacha20.NewUnauthenticatedCipher(key, padding[:12])
				length := size
				if i == 3 {
					length = 16
				}
				cipher.XORKeyStream(msg[:length], msg[:length])
				wire := append(padding, msg...)
				packets = append(packets, map[string]any{"type": i + 1, "header": h, "payload": hex.EncodeToString(wire)})
			}
		}
		cases = append(cases, map[string]any{"name": c.Name, "parameters": params, "packets": packets})
	}
	out := map[string]any{"generator": "generate_wire_vectors.go using pinned upstream x/crypto", "header_key": base64.StdEncoding.EncodeToString(key), "server_public_key": base64.StdEncoding.EncodeToString(pub), "cases": cases}
	data, _ := json.MarshalIndent(out, "", "  ")
	fmt.Println(string(data))
}
