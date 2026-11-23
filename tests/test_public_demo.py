import base64
import hashlib
import json
import re
import unittest
from unittest.mock import patch

from pipeline_ui import build_public_demo as demo


class PublicDemoTests(unittest.TestCase):
    def test_assets_are_allowlisted_and_the_graph_script_matches_pages_policy(self):
        files = demo.assets()
        self.assertEqual(set(files), {'index.html', 'studio.css', 'demo.css', 'demo.js', 'reference.js', '_headers',
            'reports/report.html', 'reports/report_plain.html', 'reports/report_graph.html', 'reports/report.json', 'reports/gdgpt_input.json'})
        graph_script, = re.findall(b'<script>(.*?)</script>', files['reports/report_graph.html'], re.S)
        self.assertIn(base64.b64encode(hashlib.sha256(graph_script).digest()), files['_headers'])
        data = json.loads(files['reference.js'].decode().removeprefix('window.BioAgentReference=').removesuffix(';\n'))
        self.assertTrue(all(len(row) == 3 and isinstance(row[2], int) for row in data['panel']))
        self.assertEqual({row[-1] for row in data['edges']}, {'NCBI'})
        self.assertEqual(next(row[5] for row in data['af'] if row[:4] == ['chr1','10397','C','A']), '0')
        self.assertNotIn('/api/', files['demo.js'].decode())

    def test_unreviewed_report_is_not_exported(self):
        with patch.dict(demo.EXAMPLE_HASHES, {'report.json': 'invalid'}):
            with self.assertRaises(ValueError):
                demo.assets()
