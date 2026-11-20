# Local QEMU Ethernet switch for Windows

English | [Русский](README.ru.md)

This helper replaces the Python switch in the isolated four-VM prefilter
lab. It learns MAC addresses and forwards QEMU's length-prefixed Ethernet
frames through a local AF_UNIX socket or a TCP listener on `127.0.0.1`.
It creates no network adapters and changes no Windows routes, firewall
settings or VPN profiles.

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

## Connect the lab NICs

Use AF_UNIX with QEMU's `stream` backend on Windows hosts that support
AF_UNIX. In two runs at 25,000 background packets/s, the switch forwarded
all frames over AF_UNIX. TCP on the same backend stalled for seconds
and filled the output queue in one run.

Start the switch before QEMU. Use a fresh socket path in a directory owned
by the lab. The full path must fit in 107 bytes.

```powershell
& "$lab\native-switch.exe" 'unix:C:\lab\cw.sock' "$lab\switch-stats.json"
```

Use `-netdev stream,id=lab,addr.type=unix,addr.path=C:/lab/cw.sock` for the
data link. Keep the Virtio device with `netdev=lab` and the management NIC.
After QEMU and the switch stop, remove the lab's socket file before
reusing its path.

For TCP loopback, run the switch with port 62590:

```powershell
& "$lab\native-switch.exe" 62590 "$lab\switch-stats.json"
```

Use `-netdev stream,id=lab,addr.type=inet,addr.host=127.0.0.1,addr.port=62590`.
The switch reports `tcp_nodelay=true` for TCP and `false` for AF_UNIX.

The switch replaces the statistics file once a second. Its path must fit
Windows `MAX_PATH` and the active code page. On each connection, `output_drops`
counts frames that did not fit in the output queue. `max_queued_send_gap_ns`
records the longest gap between writes while data was queued.
`max_pending_age_ns` measures how long the queue stayed nonempty.

## Record switch and host timing

For a load run, put the switch's statistics, optional pcap, and standard
error on a fast local disk. The JSON snapshot and pcap writes run in the
forwarding process. In the v46 control, moving these outputs away from the
VM disk kept JSON writes below the 20 ms logging threshold. [V46 measurements](../validation-v46.md)

```powershell
$scratch = 'C:\lab\switch-output'
$tap = Join-Path $scratch 'pcap'
New-Item -ItemType Directory -Force $tap | Out-Null
& "$lab\native-switch.exe" 'unix:C:\lab\cw.sock' "$scratch\switch-stats.json" $tap 2> "$scratch\switch.log"
```

The third argument enables the optional tap. Use a new capture directory
for each run. The tap opens an eight-second window when the lab client
uses the expected NAT port 42501. A later matching frame can open
another window after the first closes. The tap records the lab tunnel and
control tuples that match the fixture. The capture may contain VPN
traffic. Keep it local. Check `tap_errors` and verify that `tap_closed`
matches `tap_sequence` before using it. The `noise_output_drops` counter
counts the fixture's background frames among each port's discarded copies.

For the v51 return-path measurement, append `--return-headers` after the
capture directory. The tap also records A → client UDP and keeps at most
96 bytes per captured frame. PCAP records retain the original frame length
and host timestamp. Use the regular full-frame tap with decoders that
require complete datagrams. [V51 measurements](../validation-v51.md)

For the v56 single-move test, use `--single-move` after the capture
directory. This header-only tap opens one eight-second window on NAT port
42503. Later frames from that port cannot reopen the tap. [V56 measurements](../validation-v56.md)

Standard error records long poll, forwarding and statistics-write
intervals with QPC timestamps. A loss episode is printed when writes
resume on that output. TCP backpressure samples need Winsock headers
that expose `SIO_TCP_INFO`. Add `-DNTDDI_VERSION=0x0A000003` to the GCC
command above to enable those samples with the tested MinGW-w64 headers.
AF_UNIX forwarding and the queue counters also work without the flag.

For QEMU 11.1.3, the [stream observer patch](qemu-win32-stream-observer.patch)
logs receive gaps, Virtio read-watch pauses and main-loop waits. Apply it
with `git apply --check` and `git apply` in a QEMU source tree, then build
as shown below. To enable the independent receiver thread, set
`CW45_STREAM_RX_LOG` to a fresh local log path in the environment of the
QEMU process under observation. Use different paths for separate VM
processes. The patch applies to the lab's `stream` backend for both
socket families. [Receiver-side observations](../validation-v45.md)

Run the [host clock observer](host-clock.py) in a separate Windows process
for the whole trial. It writes the clock samples when the duration expires
or you press Ctrl+C. Use a fresh output path.

```powershell
python host-clock.py "$scratch\host-clock.json" --seconds 180
```

## BQL and Windows scheduler tracing

For the QEMU 11.1.3 lab, apply the stream observer patch first and
then the [BQL observer patch](qemu-win32-bql-observer.patch). Check
and apply each patch in the QEMU source tree. The BQL patch records
the main thread ID and elapsed acquisition and hold intervals of at
least 5 ms for the Windows SRW lock. A hold record is written when the
thread releases the lock. The measurements use QPC.

Build the two ETW tools from this directory with MinGW-w64. Use a fresh
scratch directory on a local disk with room for the trace.

```powershell
$scratch = 'C:\lab\bql-trace-01'
New-Item -ItemType Directory -Path $scratch | Out-Null
gcc -O2 -Wall -Wextra -Werror -municode scheduler-record.c -o "$scratch\scheduler-record.exe" -ladvapi32
gcc -O2 -Wall -Wextra -Werror -municode scheduler-read.c -o "$scratch\scheduler-read.exe" -ladvapi32
```

Start the recorder from an elevated PowerShell with the same
`$scratch` path after bringing up the VMs and before starting
the load.

```powershell
& "$scratch\scheduler-record.exe" "$scratch\scheduler.etl" "$scratch\stop.request" 180
```

The recorder collects scheduler metadata for the Windows host. Keep the
raw ETL local. It stops after the specified time, at 2 GiB, or when
`stop.request` appears. Create that file from another terminal to stop
the owned trace early. Check the `STOP` status and loss counts, and use
only intervals covered by the trace. An orchestrator can pass a start
marker and a status log as two extra arguments after the duration.

Decode one VM at a time. Pass its QEMU stderr log containing `CW47 main`
and `CW47 bql` records. Use PowerShell 7 for the redirection below.

```powershell
$log = Join-Path $scratch 'entry-qemu.log'
$ids = Join-Path $scratch 'entry-threads.txt'
$csv = Join-Path $scratch 'entry-scheduler.csv'
python bql-report.py threads $log | Set-Content -Encoding ascii $ids
& "$scratch\scheduler-read.exe" "$scratch\scheduler.etl" $ids > $csv
python bql-report.py report $csv $log
```

To label the vCPU, pass `--vcpu-tid` with the `thread-id` from
`query-cpus-fast` for that VM. To restrict the report to the workload, pass
`--start-ns` and `--end-ns` with the switch's `noise_first_ns` and
`noise_last_ns`. The report totals running, ready, waiting and unknown
time on each completed acquisition and shows overlapping holder intervals.
[Measurements and limits](../validation-v47.md)

## Device access and ETW wait stacks

Apply [the MMIO observer](qemu-win32-mmio-observer.patch) to the same QEMU
11.1.3 source tree as the BQL observer. `CW48 mmio` reports the region,
device type, address, direction and width for slow accesses that acquire
the BQL. The address belongs to the current address space, so it can be
an I/O port on x86. An all-ones address marks a cached access for which
only the region offset is available. The marker is written after unlock.

For a startup capture, use an elevated PowerShell with `xperf` from the
Windows Performance Toolkit. Use a scratch directory outside the
repository. Check for an existing NT Kernel Logger and leave it running if
another application owns it. Start the lab VMs after the trace is active
and stop the trace once they have initialized.

```powershell
if ((xperf -loggers) -match '^\s*Logger Name\s*:\s*NT Kernel Logger\s*$') {
    throw 'NT Kernel Logger is already running'
}
xperf -on PROC_THREAD+LOADER+CSWITCH+DISPATCHER+DISK_IO+DISK_IO_INIT+HARD_FAULTS -stackwalk CSwitch -ClockType PerfCounter -f "$scratch\startup.etl" -BufferSize 256 -MinBuffers 128 -MaxBuffers 384 -MaxFile 4096
if ($LASTEXITCODE -ne 0) { throw 'Could not start the trace' }
try { Read-Host 'Start the lab VMs in another terminal. Press Enter to stop the trace' }
finally { xperf -stop }
```

Put the main and vCPU thread IDs in `$ids` on separate lines. Get the main
TID from `CW47 main` and use the vCPU `thread-id` from QMP
`query-cpus-fast` once the monitor responds. Use the decoder built above.

```powershell
& "$scratch\scheduler-read.exe" "$scratch\startup.etl" $ids --details > "$scratch\startup.csv"
if ($LASTEXITCODE -ne 0) { throw 'Incomplete ETW decode' }
python mmio-report.py "$scratch\startup.csv" "$qemuLog" $vcpuTid > "$scratch\mmio.json"
```

Use PowerShell 7 for UTF-8 redirection. The reader retains its original CSV
format without `--details`. With the flag, it adds stack addresses, image
ranges, hard faults and disk completions. The report pairs each wait with
the next switch-in stack on the same TID and uses the image load address
to express stack frames as RVAs. For a QEMU frame, add its RVA to the PE
preferred `ImageBase` and pass that address to `addr2line -f -e` with the
unstripped diagnostic binary. For PCI config writes, `-trace
enable=pci_cfg_write` also gives the target and register. Use it only for
identification. Writing the PCI log can itself extend a BQL hold.

Keep the ETL, CSV and per-run JSON local. See the [v48 measurements](../validation-v48.md).

## Buffer COM1 on the host

Replace `-serial file:PATH` in each local lab VM's launch arguments with
these options to keep serial output off the filesystem during the test.

```text
-chardev ringbuf,id=lab-com1,size=1048576 -serial chardev:lab-com1
```

Python launchers can make the same change with
[`qemu_com1.with_ringbuf(argv)`](qemu_com1.py). Keep each VM's QMP
monitor on loopback. After the load and ETW capture end, drain the
buffer to a new file before shutting down the VM. In the example, 62622
is that VM's local QMP port and `$scratch` is outside the repository.

```powershell
python qemu_com1.py 62622 "$scratch\entry-com1.log"
```

The 1 MiB buffer overwrites its oldest bytes when full. Reading it consumes
the saved bytes. Keep the logs with the private ETW files. The [v49
report](../validation-v49.md) compares this setup with file-backed COM1.
The [v50 series](../validation-v50.md) repeats the comparison in three alternating pairs at 25,000 packets/s.

## QEMU on Windows: write each frame together

The [v11 study](../validation-v11.md) traced intermittent rate shortfalls
to QEMU's Windows socket send path. Its vectored-I/O fallback writes the
four-byte length and Ethernet frame separately. The supplied
[patch](qemu-win32-single-write.patch) combines them into one buffer and
one `send()` attempt, retaining partial-write and error handling.
The patch applies to the older `socket` backend. The `stream` setup above
works without it.
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

## Multiple noise sources

The Linux [noise sender](noise-multi-source.c) can bind up to 16 existing
addresses on the disposable `kit-restore` guest. It distributes up to 8192 UDP
sockets across them and reports successful sends per source. Its rate argument
is the total rate across all sources. The destination stays fixed at the lab
entry, `192.168.76.10:32497`; it cannot select an Internet destination.

Build and run its offline self-test in a Linux guest:

```bash
gcc -O2 -std=c11 -Wall -Wextra -Werror noise-multi-source.c -o noise-multi-source
./noise-multi-source --self-test
```

Traffic mode requires hostname `kit-restore`, the configured addresses starting
at `192.168.76.40` and an existing 256-byte fixture in `/root/prefilter`.
For example, this lab-only invocation sends 25,000 packets/s in total for
70 seconds, with 4096-packet bursts, 64 sockets and 16 source addresses:

```bash
./noise-multi-source 25000 70 4096 64 captured-prefix 16
```

V30 adds up to 8192 sockets for conntrack churn, durations up to 900 seconds
and optional source/port starts. The latter let separate processes use
disjoint lab tuples and independent burst schedules. The sender raises its
own descriptor soft limit within the existing hard limit. Addresses remain
within `192.168.76.40` through `.55`; the destination remains fixed.
The requested schedule must fit at most 16384 burst records; otherwise it
is rejected before sending.

```bash
./noise-multi-source 25000 70 4096 8192 captured-prefix 16
./noise-multi-source 6250 300 257 16 captured-prefix 4 40 40000
```

It creates no addresses or keys. The [v28 study](../validation-v28.md) checks
the per-source send counts against the switch's independent observations.

## Compact UDP sequence capture

The lab-only [collector](udp-capture.py) records each actual iperf UDP
counter and capture timestamp, including separate counters inside GSO
frames. It stores no packet bodies. Payloads are limited to 128, 512 and
1200 bytes. Fragmented UDP and truncated captures are rejected. Choose a
payload below the native profile's MTU; do not change client MTU to make a
benchmark pass.

```bash
python3 udp-capture.py --self-test
sudo install -d -m700 /root/prefilter/pingtrace/smoke
# Disposable kit-client, with the collector available at this path:
sudo ip netns exec pf-client1 python3 /path/to/udp-capture.py pf1 1200 /root/prefilter/pingtrace/smoke/udp.seq
```

Stop with SIGINT. Retain the `.seq.meta.json` completion record and tcpdump's
stderr loss report; incomplete files are not valid delivery evidence. The
collector requires root, hostname `kit-client` or `kit-exit`, and an output
under `/root/prefilter/pingtrace`. It uses installed tcpdump with immediate
mode, a 65535-byte snapshot and a 64-MiB capture ring. V30 checks its actual
counter sets and timestamps against a separate full capture at a lower
calibration rate. These private captures are ignored by Git.

## Bounds and observations

The switch accepts four peers. It learns up to 64 MAC addresses, replacing
the oldest entry when full. Unknown unicast and multicast frames go to the
other peers; learned unicast goes to its destination peer. This is Ethernet
forwarding behavior, without an access-control policy.

Each peer has a 256-KiB input buffer and a 4-MiB output ring. A full output
ring drops that destination's copy and increments `dropped`. Lengths above
65,536 bytes disconnect the sending peer; frames shorter than 14 bytes are
ignored. Valid frame bytes and their order within each destination queue
are preserved. Accepted TCP sockets use `TCP_NODELAY`.

The noise counter recognizes the lab fixture only: IPv4 without options,
UDP from `192.168.76.40` through `192.168.76.55` on any source port to `192.168.76.10:32497`,
UDP length 264.
Other traffic is forwarded normally and is absent from that counter.
This address check is telemetry, not a firewall or client allowlist.
The bounded `noise_source_frames` map has one cumulative counter for each of
the sixteen addresses. Subtract before/after snapshots to check a workload.

Arrival times use QPC, with a rolling history of 4096 nonempty 100-ms bins.
The oldest bin is evicted when full. This retains at least 409.6 seconds
of active timing history; cumulative frame counts and first/last timestamps
continue across eviction. Save the bins before a longer workload exceeds
that history. This replaces the old 20,000-bin assertion that stopped the
switch during the [v19 series](../validation-v19.md).
`max_pending_age_ns` measures a queue's nonempty period, not individual
packet latency. Counters for partial/blocked sends describe this process's
sockets; they do not measure every buffer inside QEMU or Windows.

Port counters reset when a connection closes. The source MAC labels the
current peer. Global counters retain the run totals.

This remains a lab tool. Its tests do not establish production networking
support or a maximum packet rate. Measure actual sender and arrival rates,
useful throughput, drops and whole-VM CPU together.

## Independent useful UDP

`udp-load.c` is a Linux-only workload for the disposable `kit-client` and
`kit-exit` VMs. By default it sends 360,000 sequenced packets at 6000/s over
60 seconds. The receiver runs for seven extra seconds and counts unique,
duplicate and invalid packets. To set the rate and duration, pass packets
per second (1–6000) and seconds (1–900) after the payload size. Use the same
values in `send` and `recv`. Supported payloads are
128 and 1200 bytes. The lab uses `10.8.1.1` on B, `10.8.1.2` and
`10.8.1.3` in the client namespaces, and UDP port 5201. The tool can
measure deliberate outages without a TCP control connection.

```sh
cc -O2 -std=c11 -Wall -Wextra -Werror udp-load.c -o udp-load
./udp-load --self-test
```

Start `./udp-load recv 10.8.1.1 128` as root in `kit-exit`, then run
`./udp-load send 10.8.1.2 10.8.1.1 128` in the client's VPN namespace as root.
For download, swap the sender and receiver addresses and use payload 1200.
Keep assertions enabled. The receiver uses `SO_RCVBUFFORCE` for a private
4-MiB request (8 MiB as reported by Linux); it does not change global sysctls.
This avoids losing a recovery burst in the lab application's small default
buffer. Real applications can still overflow their own buffers. Compare
inner-interface captures with receiver counts. The receiver reports
`missing_by_scheduled_second`, one count per second derived from sequence
numbers after the run. With the default rate, index 0 covers sequences 1
through 6000. The bins follow the sender's schedule and carry no capture
timestamps. Use them for delivery counts when
running without a UDP capture. See [v36](../validation-v36.md).
