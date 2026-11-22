import json
from pathlib import Path
import tempfile
import unittest

from servers import spa_access as spa


class SpaKeyTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)

    def test_generate_two_distinct_keys_and_never_overwrite(self):
        home = Path(self.directory.name)
        server, device = home / 'keys.json', home / 'device.key'
        spa.generate(server, device)
        snapshot = server.read_bytes()
        config = json.loads(snapshot)
        self.assertEqual(config['devices'], [device.read_text().strip()])
        self.assertNotIn(config['cookie_key'], config['devices'])
        with self.assertRaises(FileExistsError):
            spa.generate(server, device)
        self.assertEqual(server.read_bytes(), snapshot)
