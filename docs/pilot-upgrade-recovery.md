# Pilot SPA recovery on Debian 13

The 23 November 2026 test used three local Debian 13 amd64 VMs with one vCPU and 1 GiB of RAM each. A ran the SPA pilot and the relay. B ran AmneziaWG 3.1 under systemd, without Docker. The third VM connected through A and sent traffic through the tunnel to B.

## Startup and rollback

| Scenario | Result |
| --- | --- |
| Reboot both nodes with confirmed rules | Administrative SSH through SPA and the AmneziaWG tunnel came back. |
| Let the rollback timer expire on a stage that blocks management SSH | SSH returned on both nodes. The tunnel carried traffic while the trial rules were in effect. |
| Reboot both nodes before confirming the stage | Both nodes discarded the trial rules. SSH through SPA and tunnel traffic worked after reboot. |
| Remove A’s `active.nft` with a stale `pilot-upgrade` marker still present | The firewall loader failed closed. The protected SSH, SPA and relay services stayed down. The administrative SPA override and key file kept the same SHA-256 checksums. |
| Restore only A’s `active.nft` through the console and reboot | The existing administrative SPA key worked again. SSH to both nodes and traffic through the tunnel to B succeeded. |
| Confirm another firewall stage | The stale marker was removed. The administrative SPA files kept their checksums, and SSH and tunnel traffic still worked. |

The pilot already had its systemd dependencies in place. For a new installation, the installer adds these dependencies after confirming the firewall rules.

## Regression tests

Four regression tests ran on the Debian client VM. They cover a stale marker on its own, a rollback record that does not match a later stage, the first migration’s rollback paths, and loss of the saved policy after confirmation. The tests exercise the Bash loader with stubs for systemd and nftables. The boot and recovery scenarios above used the running services.

Run the regression tests on Linux with Bash and `flock` installed.

```bash
python3 -m unittest discover -s tests -p test_stage_lockdown.py -v
```
