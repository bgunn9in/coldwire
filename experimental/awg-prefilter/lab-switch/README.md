# Local QEMU Ethernet switch for Windows

English | [Русский](README.ru.md)

This helper replaces the Python switch in the isolated four-VM prefilter
lab. It is a learning Ethernet relay over QEMU's length-prefixed TCP
connections. It binds only to `127.0.0.1`. It creates no network adapters
and changes no Windows routes, firewall settings or VPN profiles.

It runs on the Windows lab host. The VPS installers do not deploy it.
It neither decrypts AWG nor authenticates clients.

## Build and check

Use a Windows MinGW-w64 GCC already on `PATH` and Python 3 for the tests.
From this directory in PowerShell:

```powershell
$lab = Join-Path $env:TEMP 'coldwire-native-switch'
New-Item -ItemType Directory -Force $lab | Out-Null
gcc -O2 -std=c11 -Wall -Wextra -Werror -static-libgcc native-switch.c -o "$lab\native-switch.exe" -lws2_32
python test_switch.py --binary "$lab\native-switch.exe" --workdir "$lab\selftest"
```

Keep assertions enabled. The source refuses `NDEBUG`, because checks and
checked API calls use assertions. Tests cover queue wrap and overflow,
MAC eviction/disconnection, partial/coalesced input, the maximum frame,
opaque payloads, learned unicast, the peer limit and noise counting.
The test uses localhost port 62591 and leaves its statistics in `--workdir`.

To run a lab switch on port 62590:

```powershell
& "$lab\native-switch.exe" 62590 "$lab\switch-stats.json"
```

Point each QEMU lab NIC at `socket,id=lab,connect=127.0.0.1:62590`.
The statistics path is an explicit output file: it is replaced once per
second through a temporary file. Use a path that fits Windows `MAX_PATH` and the active Windows code page;
the helper uses the ANSI path APIs.

## Bounds and observations

The switch accepts four peers. It learns up to 64 MAC addresses, replacing
the oldest entry when full. Unknown unicast and multicast frames go to the
other peers; learned unicast goes to its destination peer. This is Ethernet
forwarding behavior, without an access-control policy.

Each peer has a 256-KiB input buffer and a 4-MiB output ring. A full output
ring drops that destination's copy and increments `dropped`. Lengths above
65,536 bytes disconnect the sending peer; frames shorter than 14 bytes are
ignored. Valid frame bytes and their order within each destination queue
are preserved. `TCP_NODELAY` is enabled on accepted sockets.

The noise counter recognizes the lab fixture only: IPv4 without options,
UDP from `192.168.76.40:46000` to `192.168.76.10:32497`, UDP length 264.
Other traffic is forwarded normally and is absent from that counter.
This address check is telemetry, not a firewall or client allowlist.

Arrival times use QPC, with 100-ms bins. At most 20,000 nonempty bins fit;
the process stops on overflow instead of silently losing observations.
`max_pending_age_ns` measures a queue's nonempty period, not individual
packet latency. Counters for partial/blocked sends describe this process's
sockets; they do not measure every buffer inside QEMU or Windows.

Port counters accumulate per connection slot until restart; the source MAC
labels its current occupant. Global counters provide whole-run accounting.

This remains a lab tool. Its tests do not establish production networking
support or a maximum packet rate. Measure actual sender and arrival rates,
useful throughput, drops and whole-VM CPU together.
