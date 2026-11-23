import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest


LOADER = Path(__file__).resolve().parents[1] / 'servers/stage-lockdown.sh'


@unittest.skipUnless(sys.platform.startswith('linux') and shutil.which('bash') and shutil.which('flock'),
                     'Linux Bash and flock are required')
class PilotRollbackTests(unittest.TestCase):
    def setUp(self):
        scratch = tempfile.TemporaryDirectory()
        self.addCleanup(scratch.cleanup)
        root = Path(scratch.name)
        self.state = root / 'lockdown'
        self.state.mkdir()
        self.active = self.state / 'active.nft'
        self.pending = self.state / 'pending.nft'
        self.ticket = self.state / 'pending.timer'
        self.marker = self.state / 'pilot-upgrade'
        self.proof = self.state / 'pending.pilot-rollback'
        self.dropin = root / '50-lockdown.conf'
        confirmed = root / 'confirmed'
        confirmed.touch()
        self.candidate = root / 'candidate.nft'
        self.candidate.write_text('candidate\n')
        self.calls = root / 'systemctl.log'
        self.calls.touch()
        self.script = root / 'stage-lockdown.sh'
        source = (LOADER.read_text().replace('/etc/coldwire-lockdown', shlex.quote(str(self.state)))
                  .replace('/run/coldwire-lockdown.lock', shlex.quote(str(root / 'lock')))
                  .replace('/var/lib/coldwire-spa-pilot/confirmed', shlex.quote(str(confirmed)))
                  .replace('/etc/systemd/system/coldwire-spa-pilot.service.d/50-lockdown.conf',
                           shlex.quote(str(self.dropin)))
                  .replace('[[ $EUID == 0 ]] || exit 1', ':'))
        bin_path = root / 'bin'
        bin_path.mkdir()
        for name, command in {
            'nft': 'if [ "$1" = list ] && [ "$2" = table ]; then exit 1; fi\ncat >/dev/null',
            'systemd-run': 'exit 0',
            'systemctl': 'printf "%s\\n" "$*" >> ' + shlex.quote(str(self.calls)),
        }.items():
            fake = bin_path / name
            fake.write_text('#!/bin/sh\n' + command + '\n')
            fake.chmod(0o700)
            if name == 'systemctl':
                source = source.replace('systemctl ', shlex.quote(str(fake)) + ' ')
        self.script.write_text(source)
        self.env = dict(os.environ, PATH=str(bin_path) + os.pathsep + os.environ['PATH'])

    def run_loader(self, *args, succeeds=True):
        result = subprocess.run(['bash', str(self.script), *map(str, args)], env=self.env,
                                text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0 if succeeds else 1, result.stderr)
        return result

    def prepare_override(self):
        self.marker.touch()
        self.dropin.write_text('confirmed admin override\n')

    def test_legacy_marker_cannot_remove_override_when_confirmed_rules_are_lost(self):
        self.prepare_override()
        result = self.run_loader('load', succeeds=False)
        self.assertIn('NO_CONFIRMED_LOCKDOWN', result.stderr)
        self.assertTrue(self.marker.exists())
        self.assertEqual(self.dropin.read_text(), 'confirmed admin override\n')
        self.assertNotIn('try-restart', self.calls.read_text())

    def test_stale_marker_cannot_claim_a_later_unconfirmed_stage(self):
        self.prepare_override()
        self.active.write_text('confirmed\n')
        self.run_loader('stage', self.candidate)
        self.assertFalse(self.proof.exists())
        self.proof.write_text('different-transaction\n')
        self.active.unlink()
        self.run_loader('rollback', self.ticket.read_text().strip())
        self.assertTrue(self.dropin.exists())
        self.assertFalse(self.proof.exists())
        self.assertNotIn('try-restart', self.calls.read_text())

    def test_first_upgrade_can_still_roll_back_by_timer_or_on_boot(self):
        for action in ('rollback', 'load'):
            with self.subTest(action=action):
                self.run_loader('stage', self.candidate)
                timer = self.ticket.read_text().strip()
                self.assertEqual(self.proof.read_text(), self.ticket.read_text())
                self.prepare_override()
                if action == 'rollback':
                    self.run_loader(action, timer)
                else:
                    self.run_loader(action, succeeds=False)
                for path in (self.marker, self.dropin, self.proof, self.pending, self.ticket):
                    self.assertFalse(path.exists(), path)
                self.assertIn('try-restart coldwire-spa-pilot.service', self.calls.read_text())

    def test_confirmation_retires_marker_and_preserves_override(self):
        self.run_loader('stage', self.candidate)
        self.prepare_override()
        self.run_loader('confirm')
        self.assertEqual(self.active.read_text(), self.candidate.read_text())
        self.assertFalse(self.marker.exists())
        self.assertFalse(self.proof.exists())
        self.active.unlink()
        self.run_loader('load', succeeds=False)
        self.assertEqual(self.dropin.read_text(), 'confirmed admin override\n')


if __name__ == '__main__':
    unittest.main()
