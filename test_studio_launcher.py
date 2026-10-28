"""Offline checks for double-click launch and reuse of a running instance."""
import ast
import io
import json
import os
from pathlib import Path
import runpy
import unittest
from unittest.mock import MagicMock, patch

import uvicorn

ROOT = Path(__file__).resolve().parent


class LauncherTests(unittest.TestCase):
    def launch(self, version=None):
        response = io.BytesIO(json.dumps({'version': version}).encode())
        response.status = 200
        probe = MagicMock()
        if version:
            probe.bind.side_effect = OSError('occupied')
        completed = MagicMock(returncode=0, stdout='TCP 127.0.0.1:8010 0.0.0.0:0 LISTENING 12345')
        with patch.dict(os.environ), patch('socket.socket', side_effect=[probe, MagicMock()]), \
                patch('urllib.request.urlopen', return_value=response), \
                patch('webbrowser.open', return_value=True) as opened, \
                patch('builtins.input', return_value=''), patch('builtins.print'), \
                patch('subprocess.run', return_value=completed), patch('time.sleep'), \
                patch('threading.Thread') as thread, patch.object(uvicorn, 'run') as serve:
            try:
                namespace = runpy.run_path(str(ROOT / 'run_studio.py'), run_name='__main__')
            except SystemExit as error:
                self.assertEqual(error.code, 0)
            else:
                # Run the readiness callback synchronously without opening a real browser.
                with patch('urllib.request.urlopen') as ready:
                    health = io.BytesIO(json.dumps({'version': namespace['CURRENT_VERSION']}).encode())
                    health.status = 200
                    ready.return_value = health
                    thread.call_args.kwargs['target']()
            self.assertEqual(os.environ['STUDIO_LOCAL_SESSION'], '1')
            opened.assert_called_once_with('http://127.0.0.1:8010/')
            return serve.call_count

    def test_fresh_launch_opens_plain_url(self):
        self.assertEqual(self.launch(), 1)

    def test_existing_version_opens_without_token(self):
        tree = ast.parse((ROOT / 'run_studio.py').read_text(encoding='utf-8'))
        current = next(ast.literal_eval(node.value) for node in tree.body if isinstance(node, ast.Assign)
                       and any(isinstance(target, ast.Name) and target.id == 'CURRENT_VERSION' for target in node.targets))
        self.assertEqual(self.launch(current), 0)

    @unittest.skipUnless(os.name == 'nt', 'Windows launcher upgrade')
    def test_upgrade_continues_starting_new_server(self):
        self.assertEqual(self.launch('cases-20261010-5'), 1)
