"""LibVLC adapter. Import failures are reported in the application window."""
import ctypes
import hashlib
import logging
import os
from pathlib import Path


def dvd_drives() -> list[str]:
    if os.name != "nt":
        return []
    return [f"{chr(n)}:\\" for n in range(65, 91)
            if ctypes.windll.kernel32.GetDriveTypeW(f"{chr(n)}:\\") == 5]


def dvd_name(source: str) -> str:
    if os.name == "nt" and len(source) >= 2 and source[1] == ":":
        root = source[:2] + "\\"
        label = ctypes.create_unicode_buffer(261)
        if ctypes.windll.kernel32.GetVolumeInformationW(root, label, len(label),
                                                        None, None, None, None, 0) and label.value:
            return label.value
    directory = Path(source)
    if directory.name.upper() == "VIDEO_TS":
        directory = directory.parent
    return directory.name or "DVD"


def media_identity(drive: str) -> str:
    """Hash DVD navigation files; fail closed rather than reuse a wrong cache."""
    root = Path(drive) / "VIDEO_TS"
    files = sorted(root.glob("*.IFO"))
    if not files:
        raise ValueError("DVDの管理情報を確認できません。DVD-Videoを挿入してください。")
    digest = hashlib.sha256()
    for file in files:
        digest.update(file.name.upper().encode("ascii"))
        with file.open("rb") as stream:
            for block in iter(lambda: stream.read(65536), b""):
                digest.update(block)
    return digest.hexdigest()


class Player:
    def __init__(self, handle: int):
        self._dll_handle = None
        if os.name == "nt":
            candidates = [os.environ.get("VLC_HOME", "")]
            tools = Path(__file__).resolve().parents[2] / ".tools"
            candidates += [str(path) for path in sorted(tools.glob("vlc-*"), reverse=True) if path.is_dir()]
            candidates += [str(Path(os.environ.get(name, "")) / "VideoLAN" / "VLC")
                           for name in ("ProgramFiles", "ProgramFiles(x86)")]
            for candidate in candidates:
                if candidate and (Path(candidate) / "libvlc.dll").is_file():
                    self._dll_handle = os.add_dll_directory(candidate)
                    ctypes.CDLL(str(Path(candidate) / "libvlc.dll"))
                    os.environ.setdefault("PYTHON_VLC_LIB_PATH", str(Path(candidate) / "libvlc.dll"))
                    os.environ.setdefault("PYTHON_VLC_MODULE_PATH", str(Path(candidate) / "plugins"))
                    os.environ.setdefault("VLC_PLUGIN_PATH", str(Path(candidate) / "plugins"))
                    break
        import vlc
        self.vlc = vlc
        self.instance = vlc.Instance("--no-video-title-show", "--quiet", "--no-spu")
        if self.instance is None:
            raise RuntimeError("VLCの初期化に失敗しました。")
        self.player = self.instance.media_player_new()
        self.media = None
        if os.name == "nt":
            self.player.set_hwnd(handle)
        self.player.audio_set_volume(70)

    def open(self, drive: str, title: int = 0, *, volume: int | None = None):
        self.player.stop()
        if self.media:
            self.media.release()
        location = Path(drive).resolve().as_uri().replace("file:", "dvd:", 1).rstrip("/")
        self.media = self.instance.media_new(f"{location}/#{title + 1}")
        self.player.set_media(self.media)
        if volume is not None:
            self.player.audio_set_volume(volume)
        if self.player.play() == -1:
            raise RuntimeError("DVDの再生を開始できませんでした。")

    def prepare(self, volume: int, include_titles: bool):
        titles = self.titles() if include_titles else []
        self.player.video_set_spu(-1)
        self.pause()
        # Opening a DVD title already starts at its beginning. A second time
        # seek while paused can stall DVD input and is unnecessary here.
        self.player.audio_set_volume(volume)
        return titles

    def titles(self):
        descriptions = self.player.get_full_title_descriptions() or []
        # VLC's index zero is the DVD menu; real DVD titles start at index one.
        return [(i - 1, description.duration) for i, description in enumerate(descriptions)
                if i > 0 and not (description.flags & 1)]

    def play(self):
        if self.player.play() == -1:
            raise RuntimeError("再生を開始できませんでした。")

    def pause(self):
        self.player.set_pause(1)

    def seek(self, ms: int):
        if self.player.set_time(ms) == -1:
            raise RuntimeError("再生位置を変更できませんでした。")

    def change_chapter(self, delta: int, resume: bool | None = None):
        """Run on the navigation worker, never on the GUI thread."""
        logger = logging.getLogger("dvd_player")
        logger.info("CHAPTER_QUERY delta=%s", delta)
        target = self.player.get_chapter() + delta
        if not 0 <= target < self.player.get_chapter_count():
            return
        if resume is None:
            resume = bool(self.player.is_playing())
        logger.info("CHAPTER_MOVE target=%s resume=%s", target, resume)
        # Use DVD navigation rather than converting chapter offsets to a time
        # seek. Do not hold up Qt's event loop while LibVLC changes the input.
        self.player.set_chapter(target)
        self.play() if resume else self.pause()
        logger.info("CHAPTER_DONE target=%s", target)

    def close(self):
        self.player.stop()
        self.player.release()
        if self.media:
            self.media.release()
        self.instance.release()
        if self._dll_handle:
            self._dll_handle.close()
