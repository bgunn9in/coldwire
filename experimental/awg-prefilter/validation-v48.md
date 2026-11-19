# V48. Devices holding the BQL during QEMU startup

English | [Русский](validation-v48.ru.md)

On the entry VM, the longest vCPU hold occurred during a write to COM1 (PIO port `0x3F8`). It held the BQL for 186.52 ms and spent 186.39 ms waiting. QEMU's main thread waited 158.23 ms to acquire the lock. The stack leads from `serial_xmit` to `win_chr_write`, which calls synchronous `WriteFile` on the host's serial log. The Windows stack includes NTFS. The other three VMs also had waits in this path, up to 86.69 ms.

## MMIO on the entry VM

| Device and address | BQL held | vCPU waiting | Call on the wait stack |
| --- | ---: | ---: | --- |
| ICH9 AHCI write, `0xFEBD4238` | 20.11 ms | 20.04 ms | `ide_cmd_permitted` |
| ICH9 AHCI read, `0xFEBD4004` | 15.18 ms | 15.13 ms | `ahci_mem_read_32` |
| Virtio-net status write, `0xFE000014` | 15.82 ms | 15.70 ms | `virtio_net_receive` |
| Virtio-blk queue enable, `0xFE00801C` | 15.09 ms | 15.03 ms | `virtio_queue_set_num` |

For each wait, a HardFault on the vCPU thread targeted a page in the QEMU executable. A host disk read covered the wait to within 0.1 ms. The same mechanism appeared during port I/O to the RTC (53.50 ms waiting), i8042 (33.16 ms) and VGA (20.65 ms). [ETW HardFault event](https://learn.microsoft.com/en-us/windows/win32/etw/pagefault-hardfault)

## PCI configuration

During firmware startup, port writes to `0xCFC` held the BQL for up to 34.67 ms in the first run. The second run identified corresponding writes as PAM register updates at `0x90` and `0x94` on the Q35 memory controller (`00:00.0`). A write through PCIe MMIO at `0xB0000090` held the lock for up to 27.92 ms. ETW showed the vCPU in Running for nearly those entire intervals. QEMU updates its memory map in this path. The scheduler trace does not split the running time by function.

The second run also recorded a 118.17 ms lock hold while writing a BAR on Virtio-net (`00:03.0`) through `0xCFC` on the exit VM. The wait stack was in `trace_pci_cfg_write → qemu_log`. The diagnostic was writing its own log under the BQL. Two shorter waits through PCIe MMIO hit the same logging path.

## Capture limits

The two startup captures used four local QEMU 11.1.3/WHPX VMs with one vCPU and 1024 MiB each, no CPU quota, and QEMU stream over AF_UNIX. The client profiles were unchanged. The 58.64 s and 99.54 s traces contained 3,313,584 and 5,381,554 context switches, respectively. Both ETL headers reported zero lost events. A known SRW lock wait calibrated stack matching at 350.13 ms and 350.09 ms.

The first run ended on an early QMP timeout. The second ended when AWG failed to start within the exit VM's setup timeout. Neither run reached the packet-rate workload. During setup on the exit VM, stream receive was paused for 10.606 s after QEMU queued a frame for the guest. There was no recorded vCPU hold or main-thread acquisition of the BQL of at least 5 ms during that interval. The cause of the historical 14.4 s pause remains open.

[MMIO and ETW capture instructions](lab-switch/README.md#device-access-and-etw-wait-stacks)
