"""DVD bitmap subtitle extraction using FFmpeg's dvdvideo and sub2video path."""
import hashlib
import json
import os
import re
from pathlib import Path
import shutil
import subprocess
import tempfile
import threading
import time

from PySide6.QtGui import QImage
from dvd_player.playback import media_identity


class ExtractionCancelled(Exception):
    pass


def find_tool(name: str) -> str:
    configured = os.environ.get("FFMPEG_HOME")
    candidates = [Path(configured) / f"{name}.exe"] if configured else []
    tools = Path(__file__).resolve().parents[2] / ".tools"
    candidates.extend(sorted(tools.glob(f"ffmpeg-*/bin/{name}.exe"), reverse=True))
    for candidate in candidates:
        if candidate.is_file():
            return str(candidate)
    found = shutil.which(name)
    if found:
        return found
    raise ValueError("DVD対応FFmpegがありません。FFmpeg導入.ps1を実行してください。")


def run_tool(args: list[str], cancel: threading.Event, timeout: int = 900,
             image_directory: Path | None = None) -> bytes:
    """No shell, bounded output, cancellable child process, no leaked DVD paths in logs."""
    with tempfile.TemporaryFile() as output:
        process = subprocess.Popen(args, stdout=output, stderr=subprocess.DEVNULL,
                                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        started = time.monotonic()
        checked = started
        try:
            while process.poll() is None:
                if cancel.wait(0.1):
                    raise ExtractionCancelled()
                if time.monotonic() - started > timeout:
                    raise ValueError("字幕取得が時間上限を超えました。媒体を確認してください。")
                if output.tell() > 16 * 1024 * 1024:
                    raise ValueError("外部ツールの出力が大きすぎます。")
                if image_directory is not None and time.monotonic() - checked > 1:
                    checked = time.monotonic()
                    files = list(image_directory.glob("*.png"))
                    if len(files) > 100000 or sum(p.stat().st_size for p in files) > 512 * 1024 * 1024:
                        raise ValueError("抽出画像が容量上限を超えました。")
            if cancel.is_set():
                raise ExtractionCancelled()
            if process.returncode:
                raise ValueError("DVDから字幕を読み出せません。対応形式・媒体・アクセス条件を確認してください。")
            output.seek(0)
            return output.read(16 * 1024 * 1024)
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=3)


def dvd_input(source: str, title_id: int) -> list[str]:
    if type(title_id) is not int or title_id < 0:
        raise ValueError("タイトル番号が不正です。")
    # Keep initial padding cells so that time zero matches title playback.
    if re.fullmatch(r"[A-Za-z]:[\\/]*", source):
        source = source[:2]
    return ["-f", "dvdvideo", "-title", str(title_id + 1), "-trim", "0", "-i", source]


def render_command(ffmpeg: str, inputs: list[str], stream_index: int, directory: Path):
    return [ffmpeg, "-hide_banner", "-loglevel", "error", "-nostdin", "-y",
            "-copyts", "-start_at_zero", *inputs,
            "-filter_complex", f"[0:{int(stream_index)}]null[subs]", "-map", "[subs]",
            "-c:v", "png", "-pix_fmt", "rgba", "-fps_mode", "passthrough",
            "-enc_time_base", "1:1000", "-frame_pts", "1", str(directory / "%012d.png")]


def bitmap_bounds(image: QImage):
    image = image.convertToFormat(QImage.Format.Format_RGBA8888)
    width, height = image.width(), image.height()
    if not 0 < width <= 4096 or not 0 < height <= 4096:
        raise ValueError("字幕画像の寸法が不正です。")
    raw = bytes(image.constBits())
    stride = image.bytesPerLine()
    left, top, right, bottom = width, height, 0, 0
    for y in range(height):
        alpha = raw[y * stride + 3:y * stride + width * 4:4]
        if alpha.strip(b"\0"):
            top = min(top, y)
            bottom = y + 1
            left = min(left, width - len(alpha.lstrip(b"\0")))
            right = max(right, len(alpha.rstrip(b"\0")))
    if bottom == 0:
        return None
    return image.copy(left, top, right - left, bottom - top)


def frames_to_manifest(directory: Path, media_id: str, title_id: int, language: str,
                       track_id: str, duration_ms: int | None, cancel: threading.Event) -> Path:
    """Transparent frames end a cue; repeated identical images do not create new cues."""
    files = sorted((p for p in directory.glob("*.png") if p.stem.lstrip("-").isdigit()),
                   key=lambda path: int(path.stem))
    cues = []
    current = None
    previous_time = -1
    for path in files:
        if cancel.is_set():
            raise ExtractionCancelled()
        position = int(path.stem)
        if position < 0:
            continue
        if position <= previous_time:
            raise ValueError("字幕画像の時刻が重複しています。")
        previous_time = position
        image = QImage(str(path))
        if image.isNull():
            raise ValueError("抽出した字幕画像を読み込めません。")
        cropped = bitmap_bounds(image)
        digest = None if cropped is None else hashlib.sha256(
            bytes(cropped.constBits()) + f"{cropped.width()}:{cropped.height()}".encode()).hexdigest()
        if current and digest == current["digest"]:
            continue
        if current:
            if position > current["start_ms"]:
                cues.append(dict(cue_id=f"cue-{len(cues):06}", start_ms=current["start_ms"],
                                 end_ms=position, image_path=current["image_path"]))
            current = None
        if cropped is not None:
            target = f"cue-{len(cues):06}.png"
            if not cropped.save(str(directory / target)):
                raise OSError("字幕画像を保存できません。")
            current = dict(start_ms=position, image_path=target, digest=digest)
    if current:
        if duration_ms is None or duration_ms <= current["start_ms"]:
            raise ValueError("最後の字幕の終了時刻を確認できません。")
        cues.append(dict(cue_id=f"cue-{len(cues):06}", start_ms=current["start_ms"],
                         end_ms=duration_ms, image_path=current["image_path"]))
    if len(cues) > 100000:
        raise ValueError("字幕の件数が上限を超えました。")
    data = dict(schema_version=1, media_id=media_id, title_id=title_id, language=language,
                track_id=track_id, complete=True, cues=cues)
    manifest = directory / "manifest.json"
    manifest.write_text(json.dumps(data), encoding="utf-8")
    return manifest


class DvdSubtitleExtractor:
    def __init__(self, cache):
        self.cache = cache

    def extract(self, source: str, media_id: str, title_id: int, cancel: threading.Event, notify):
        ffmpeg, ffprobe = find_tool("ffmpeg"), find_tool("ffprobe")
        if cancel.is_set():
            raise ExtractionCancelled()
        if media_identity(source) != media_id:
            raise ValueError("DVDが変更されています。読み込み直してください。")
        formats = run_tool([ffmpeg, "-hide_banner", "-demuxers"], cancel, 20).decode(errors="replace")
        if "dvdvideo" not in formats:
            raise ValueError("このFFmpegはDVD非対応です。libdvdnav/libdvdread入りのfull版が必要です。")
        metadata = run_tool([ffprobe, "-v", "error", *dvd_input(source, title_id),
                             "-show_streams", "-show_format", "-of", "json"], cancel, 90)
        data = json.loads(metadata)
        streams = [stream for stream in data.get("streams", []) if stream.get("codec_type") == "subtitle"]
        duration = data.get("format", {}).get("duration")
        duration_ms = round(float(duration) * 1000) if duration is not None else None
        results = []
        unknown = []
        for stream in streams:
            code = stream.get("tags", {}).get("language", "und").lower()
            language = {"eng": "en", "en": "en", "jpn": "ja", "ja": "ja"}.get(code)
            if language is None:
                unknown.append(stream["index"])
                continue
            if stream.get("codec_name") != "dvd_subtitle":
                continue
            if cancel.is_set():
                raise ExtractionCancelled()
            notify("progress", f"{'英語' if language == 'en' else '日本語'}字幕を取得中…")
            with tempfile.TemporaryDirectory(prefix="dvd-subtitles-") as temp:
                directory = Path(temp)
                command = render_command(ffmpeg, dvd_input(source, title_id), stream["index"], directory)
                run_tool(command, cancel, image_directory=directory)
                if media_identity(source) != media_id:
                    raise ValueError("取得中にDVDが変更されました。読み込み直してください。")
                manifest = frames_to_manifest(directory, media_id, title_id, language,
                                               str(stream["index"]), duration_ms, cancel)
                track, warning = self.cache.import_manifest(manifest, media_id, title_id)
                if warning:
                    # The temporary directory cannot be used after this worker finishes.
                    raise ValueError("抽出字幕を保存できません。空き容量・保存先を確認してください。")
                results.append(track)
                notify("track", track)
        return results, unknown
