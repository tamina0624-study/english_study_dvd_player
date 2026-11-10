"""Capture Python/native call boundaries when the GUI stops responding."""
import faulthandler
from pathlib import Path

from PySide6.QtCore import QTimer


def dump_threads(root: Path):
    try:
        directory = root / "logs"
        directory.mkdir(parents=True, exist_ok=True)
        with (directory / "freeze.log").open("ab") as stream:
            faulthandler.dump_traceback(file=stream, all_threads=True)
    except OSError:
        pass


def install_hang_diagnostics(app, root: Path):
    """Qt renews the deadline; a blocked event loop leaves it to expire."""
    try:
        directory = root / "logs"
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / "freeze.log"
        if path.exists() and path.stat().st_size > 2 * 1024 * 1024:
            path.replace(directory / "freeze.previous.log")
        stream = path.open("ab")
    except OSError:
        return

    def renew():
        faulthandler.dump_traceback_later(10, repeat=True, file=stream)

    timer = QTimer(app)
    timer.setInterval(1000)
    timer.timeout.connect(renew)

    def stop():
        timer.stop()
        faulthandler.cancel_dump_traceback_later()
        stream.close()

    app.aboutToQuit.connect(stop)
    renew()
    timer.start()
