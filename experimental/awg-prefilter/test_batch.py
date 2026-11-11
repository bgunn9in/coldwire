"""Check exact packet IDs and verdict bytes through a mocked netlink sender."""
import os
from pathlib import Path
import struct
import subprocess
import unittest

import test_prefilter as fixtures

DRIVER = Path(os.environ.get('PREFILTER_BATCH_DRIVER', str(fixtures.HERE / 'test-batch'))).resolve()


class BatchTests(fixtures.PrefilterTests):
    def records(self, ids):
        good = fixtures.packet(bytes.fromhex(fixtures.VECTORS['1']) + bytes(512))
        bad = bytearray(good)
        bad[58] ^= 1
        return [(number, good if index % 2 == 0 else bytes(bad)) for index, number in enumerate(ids)]

    def run_batch(self, records, mode='', expected_code=0):
        raw = b''.join(struct.pack('!III', number, len(packet), min(len(packet), 212)) + packet[:212]
                       for number, packet in records)
        result = subprocess.run([str(DRIVER), str(self.key)], input=raw, capture_output=True,
                                env=dict(os.environ, BATCH_TEST_SEND=mode))
        self.assertEqual(result.returncode, expected_code, result.stderr.decode(errors='replace'))
        verdicts = []
        batches = []
        for line in result.stdout.splitlines():
            wire = bytes.fromhex(line.decode())
            count = 0
            while wire:
                length, message_type, flags, sequence, port_id = struct.unpack_from('=IHHII', wire)
                self.assertEqual(length, 32)
                self.assertEqual(message_type, (3 << 8) | 1)  # Individual NFQNL_MSG_VERDICT.
                self.assertEqual(flags, 1)  # NLM_F_REQUEST without success acknowledgements.
                family, version, queue = struct.unpack_from('!BBH', wire, 16)
                self.assertEqual((family, version, queue), (0, 0, 100))
                attr_length, attr_type = struct.unpack_from('=HH', wire, 20)
                self.assertEqual((attr_length, attr_type), (12, 2))
                verdict, number = struct.unpack_from('!II', wire, 24)
                verdicts.append((number, verdict))
                wire = wire[length:]
                count += 1
            self.assertLessEqual(count, 16)
            batches.append(count)
        return verdicts, batches

    def test_mixed_packets_receive_individual_verdicts(self):
        records = self.records(range(1, 34))
        verdicts, batches = self.run_batch(records)
        self.assertEqual(verdicts, [(number, int(index % 2 == 0)) for index, (number, _) in enumerate(records)])
        self.assertEqual(batches, [16, 16, 1])

    def test_gaps_wrap_and_out_of_order_ids_are_preserved(self):
        records = self.records([0xfffffffe, 0xffffffff, 0, 1, 900, 8, 0x80000000])
        verdicts, batches = self.run_batch(records)
        self.assertEqual(verdicts, [(number, int(index % 2 == 0)) for index, (number, _) in enumerate(records)])
        self.assertEqual(batches, [len(records)])

    def test_interrupted_send_retries_the_same_datagram_once(self):
        records = self.records(range(33))
        verdicts, batches = self.run_batch(records, mode='eintr')
        self.assertEqual(verdicts, [(number, int(index % 2 == 0)) for index, (number, _) in enumerate(records)])
        self.assertEqual(batches, [16, 16, 1])

    def test_failed_send_emits_no_verdicts(self):
        self.assertEqual(self.run_batch(self.records(range(6)), mode='failure', expected_code=1), ([], []))

    def test_failure_after_a_flush_keeps_unsent_packets_unapproved(self):
        records = self.records(range(33))
        verdicts, batches = self.run_batch(records, mode='failure-after-first', expected_code=1)
        self.assertEqual(verdicts, [(number, int(index % 2 == 0)) for index, (number, _) in enumerate(records[:16])])
        self.assertEqual(batches, [16])

    def test_unexpected_short_datagram_send_is_fatal(self):
        self.assertEqual(self.run_batch(self.records(range(6)), mode='short', expected_code=1), ([], []))

    def test_idle_input_emits_no_verdict(self):
        self.assertEqual(self.run_batch([]), ([], []))


if __name__ == '__main__':
    unittest.main(verbosity=2)
