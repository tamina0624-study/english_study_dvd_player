"""Short-lived DVD I/O helper; the parent can terminate blocked device reads."""
import sys
from pathlib import Path

from dvd_player.playback import media_identity


def main():
    if len(sys.argv) != 3 or sys.argv[1] not in ("identity", "present"):
        return 2
    operation, drive = sys.argv[1:]
    try:
        if operation == "identity":
            print(media_identity(drive))
        else:
            print("1" if (Path(drive) / "VIDEO_TS" / "VIDEO_TS.IFO").is_file() else "0")
        return 0
    except OSError:
        return 1


if __name__ == "__main__":
    sys.exit(main())
