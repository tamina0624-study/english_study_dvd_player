"""Local Subtitle Edit interchange: SRT text and BDN XML image subtitles."""
import html
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET

from PySide6.QtGui import QImageReader
from dvd_player.core import Cue, CueIndex


TIME = r"(\d{2,}):([0-5]\d):([0-5]\d)[,.](\d{1,3})"
TIMELINE = re.compile(r"^" + TIME + r"\s*-->\s*" + TIME + r"(?:\s+.*)?$")


def parse_srt(path: Path) -> CueIndex:
    if path.stat().st_size > 20 * 1024 * 1024:
        raise ValueError("SRTファイルが大きすぎます。")
    raw = path.read_bytes()
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        content = raw.decode("utf-16")
    else:
        try:
            content = raw.decode("utf-8-sig")
        except UnicodeDecodeError:
            try:
                content = raw.decode("cp932")
            except UnicodeDecodeError as error:
                raise ValueError("SRTをUTF-8で保存し直してください。") from error
    cues = []
    blocks = re.split(r"\n\s*\n", content.replace("\r\n", "\n").replace("\r", "\n").strip())
    for number, block in enumerate(blocks, 1):
        lines = block.strip().splitlines()
        if not lines:
            continue
        if lines[0].strip().isdigit():
            lines = lines[1:]
        match = TIMELINE.fullmatch(lines[0].strip()) if lines else None
        if not match or len(lines) < 2:
            raise ValueError(f"SRTの{number}番目の字幕形式が不正です。")
        values = match.groups()
        def milliseconds(parts):
            hours, minutes, seconds, fraction = parts
            return ((int(hours) * 60 + int(minutes)) * 60 + int(seconds)) * 1000 + int(fraction.ljust(3, "0"))
        start, end = milliseconds(values[:4]), milliseconds(values[4:])
        text = "\n".join(lines[1:]).strip()
        text = re.sub(r"<br\s*/?>", "\n", text, flags=re.I)
        text = html.unescape(re.sub(r"</?(?:i|b|u|font)(?:\s[^>]*)?>", "", text, flags=re.I))
        if end <= start or not text.strip() or len(text) > 10000:
            raise ValueError(f"SRTの{number}番目の字幕の時刻または本文が不正です。")
        cues.append(Cue(f"srt-{number:06}", start, end, text=text))
        if len(cues) > 100000:
            raise ValueError("字幕の件数が上限を超えました。")
    if not cues:
        raise ValueError("SRTに字幕がありません。")
    return CueIndex(cues)


def srt_time(ms):
    seconds, fraction = divmod(ms, 1000)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    return f"{hours:02}:{minutes:02}:{seconds:02},{fraction:03}"


def bdn_time(ms):
    # The exchange file uses a 25fps grid, with at most 20ms rounding error.
    frames = (ms * 25 + 500) // 1000
    seconds, frame = divmod(frames, 25)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    return f"{hours:02}:{minutes:02}:{seconds:02}:{frame:02}"


def export_for_editor(index: CueIndex, language: str, parent: Path, prefix: str | None = None) -> Path:
    if not index.cues:
        raise ValueError("書き出せる字幕がありません。")
    if language not in ("en", "ja"):
        raise ValueError("字幕の言語が不正です。")
    # Always create a new folder; never overwrite a user's existing export.
    parent = Path(parent)
    parent.mkdir(parents=True, exist_ok=True)
    directory = Path(tempfile.mkdtemp(prefix=prefix or f"dvd-subtitles-{language}-", dir=parent))
    if all(cue.text is not None for cue in index.cues):
        path = directory / f"subtitles.{language}.srt"
        content = "\n\n".join(f"{n}\n{srt_time(c.start_ms)} --> {srt_time(c.end_ms)}\n{c.text}"
                               for n, c in enumerate(index.cues, 1))
        path.write_text(content + "\n", encoding="utf-8-sig")
        return path
    if any(cue.image is None for cue in index.cues):
        raise ValueError("画像と文字が混在した字幕は書き出せません。")
    root = ET.Element("BDN", Version="0.93")
    description = ET.SubElement(root, "Description")
    ET.SubElement(description, "Name", Title=f"DVD subtitles {language}", Content="")
    ET.SubElement(description, "Language", Code="eng" if language == "en" else "jpn")
    ET.SubElement(description, "Format", VideoFormat="1080p", FrameRate="25", DropFrame="False")
    ET.SubElement(description, "Events", Type="Graphic", FirstEventInTC=bdn_time(index.cues[0].start_ms),
                  LastEventOutTC=bdn_time(max(c.end_ms for c in index.cues)), NumberofEvents=str(len(index.cues)))
    events = ET.SubElement(root, "Events")
    for number, cue in enumerate(index.cues):
        size = QImageReader(str(cue.image)).size()
        if not size.isValid() or max(size.width(), size.height()) > 4096:
            raise ValueError("字幕画像を読み込めません。")
        name = f"{number:06}.png"
        shutil.copyfile(cue.image, directory / name)
        start = bdn_time(cue.start_ms)
        end = bdn_time(cue.end_ms)
        if end == start:
            end = bdn_time(cue.start_ms + 40)
        event = ET.SubElement(events, "Event", InTC=start, OutTC=end, Forced="False")
        ET.SubElement(event, "Graphic", Width=str(size.width()), Height=str(size.height()), X="0", Y="0").text = name
    path = directory / f"subtitles.{language}.xml"
    ET.indent(root)
    ET.ElementTree(root).write(path, encoding="utf-8", xml_declaration=True)
    return path


def find_editor() -> Path | None:
    candidates = [Path(os.environ["SUBTITLE_EDIT_PATH"])] if os.environ.get("SUBTITLE_EDIT_PATH") else []
    tools = Path(__file__).resolve().parents[2] / ".tools"
    candidates.extend(tools.glob("SubtitleEdit*/SubtitleEdit.exe"))
    for variable in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
        if os.environ.get(variable):
            for folder in ("Subtitle Edit", "SubtitleEdit", "Programs/Subtitle Edit"):
                candidates.append(Path(os.environ[variable]) / folder / "SubtitleEdit.exe")
    located = shutil.which("SubtitleEdit.exe")
    if located:
        candidates.append(Path(located))
    return next((path for path in candidates if path.is_file()), None)


def launch_editor(executable: Path, subtitle: Path):
    if not executable.is_file() or executable.suffix.lower() != ".exe":
        raise ValueError("Subtitle Editの実行ファイルを選択してください。")
    if not subtitle.is_file():
        raise ValueError("字幕ファイルが見つかりません。")
    return subprocess.Popen([str(executable), str(subtitle)],
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
