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
opaque payloads, learned unicast, the peer limit, noise counting and expiry
of the oldest timing bins. A rejected connection may close with EOF or reset.
The test uses localhost port 62591 and leaves its statistics in `--workdir`.

To run a lab switch on port 62590:

```powershell
& "$lab\native-switch.exe" 62590 "$lab\switch-stats.json"
```

Point each QEMU lab NIC at `socket,id=lab,connect=127.0.0.1:62590`.
The statistics path is an explicit output file: it is replaced once per
second through a temporary file. Use a path that fits Windows `MAX_PATH` and the active Windows code page;
the helper uses the ANSI path APIs.

## QEMU on Windows: write each frame together

The [v11 study](../validation-v11.md) traced intermittent rate shortfalls
to QEMU's Windows socket send path. Its vectored-I/O fallback writes the
four-byte length and Ethernet frame separately. The supplied
[patch](qemu-win32-single-write.patch) combines them into one buffer and
one `send()` attempt, retaining partial-write and error handling.
It changes the lab's QEMU executable; the switch and VPS code are unchanged.
TCP remains a byte stream and can still split or combine reads.

The patch was tested with QEMU 11.1.3. Use an already configured Windows
QEMU source/build tree and the MinGW-w64 compiler used for that build.
From this directory, set the paths to your own source and build trees:

```powershell
$lab = Join-Path $env:TEMP 'coldwire-native-switch'
$qemuSource = 'C:\src\qemu-11.1.3'
$qemuBuild = 'C:\src\qemu-build'
$patch = (Resolve-Path '.\qemu-win32-single-write.patch').Path
git -C $qemuSource apply --check $patch
if ($LASTEXITCODE -ne 0) { throw 'Patch does not match this QEMU source' }
git -C $qemuSource apply $patch
if ($LASTEXITCODE -ne 0) { throw 'Patch application failed' }
python test_qemu_stream.py --source "$qemuSource\net\socket.c" --workdir "$lab\stream-test"
if ($LASTEXITCODE -ne 0) { throw 'Stream regression test failed' }
ninja -C $qemuBuild qemu-system-x86_64.exe
if ($LASTEXITCODE -ne 0) { throw 'QEMU build failed' }
```

Stop the lab VMs before replacing their executable. Start them with the
rebuilt executable and retain `TCP_NODELAY` on both ends. These commands
assume an existing QEMU build; they do not configure its dependencies or
include the earlier lab's WHPX compatibility changes.

The regression test compiles the actual `net_socket_receive` function
against bounded fake I/O. It checks one write per complete frame, exact
bytes, partial retries, `EAGAIN`, zero writes, fatal errors, zero/maximum
payloads and allocation cleanup. The original Windows implementation
fails the one-write assertion. The test uses no sockets or VM resources.

## Fixed ICMP measurements

[v12](../validation-v12.md) shows that a legacy `ping -c100 -i0.02 -W1`
can finish before its last delayed reply arrives. The optional
[ICMP helper](icmp-probe.py) sends exactly 100 IPv4 echo requests to the lab
exit `10.8.1.1`, with 56-byte payloads and 20-ms pacing. It uses an explicit
one-second reply budget and reports JSON. It changes no interfaces or routes
and is not deployed to VPS or physical clients.

Run its offline self-test anywhere with Python 3 and assertions enabled;
`python -O` is unsupported. VM mode requires Linux root with `CAP_NET_RAW`
and an existing lab namespace. From this directory:

```bash
python3 icmp-probe.py --self-test
sudo ip netns exec pf-client1 python3 icmp-probe.py --vm-test
```

Exit status is zero only when all 100 replies arrive within the budget.
JSON identifies missing sequences, late replies and duplicates. Validate
the result and stderr: a startup/socket error is a failed measurement,
not a packet-loss result. Live regression controls accepted a delayed last
reply and detected a deliberately dropped request. The probe does not
replace whole-VM CPU, offered-rate or packet-capture checks.

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
UDP from `192.168.76.40` on any source port to `192.168.76.10:32497`,
UDP length 264.
Other traffic is forwarded normally and is absent from that counter.
This address check is telemetry, not a firewall or client allowlist.

Arrival times use QPC, with a rolling history of 4096 nonempty 100-ms bins.
The oldest bin is evicted when full. This retains at least 409.6 seconds
of active timing history; cumulative frame counts and first/last timestamps
continue across eviction. Save the bins before a longer workload exceeds
that history. This replaces the old 20,000-bin assertion that stopped the
switch during the [v19 series](../validation-v19.md).
`max_pending_age_ns` measures a queue's nonempty period, not individual
packet latency. Counters for partial/blocked sends describe this process's
sockets; they do not measure every buffer inside QEMU or Windows.

Port counters accumulate per connection slot until restart; the source MAC
labels its current occupant. Global counters provide whole-run accounting.

This remains a lab tool. Its tests do not establish production networking
support or a maximum packet rate. Measure actual sender and arrival rates,
useful throughput, drops and whole-VM CPU together.
