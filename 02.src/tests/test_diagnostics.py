from pathlib import Path
import os
import subprocess
import sys
import tempfile
import unittest


class DiagnosticsTests(unittest.TestCase):
    def test_blocked_gui_records_stack_without_gui_timer_running(self):
        code = '''
import faulthandler
from pathlib import Path
import sys
import time
from unittest.mock import patch
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from dvd_player.diagnostics import install_hang_diagnostics

app = QApplication([])
original = faulthandler.dump_traceback_later
def short_deadline(*args, **kwargs):
    original(.2, **kwargs)
def blocked_gui():
    time.sleep(.5)
    app.quit()
with patch('faulthandler.dump_traceback_later', side_effect=short_deadline):
    install_hang_diagnostics(app, Path(sys.argv[1]))
    QTimer.singleShot(0, blocked_gui)
    app.exec()
'''
        with tempfile.TemporaryDirectory() as directory:
            result = subprocess.run([sys.executable, "-c", code, directory],
                                    env={**os.environ, "QT_QPA_PLATFORM": "offscreen"},
                                    capture_output=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr.decode(errors="replace"))
            trace = (Path(directory) / "logs" / "freeze.log").read_text(encoding="utf-8")
            self.assertIn("blocked_gui", trace)
