"""Local, bounded subtitle cache and privacy-conscious application logging."""
from dataclasses import dataclass
import hashlib
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import re
import shutil
import tempfile
import threading
from functools import wraps

from dvd_player.core import CueIndex, read_manifest


def serialized(method):
    @wraps(method)
    def call(self, *args, **kwargs):
        with self.lock:
            return method(self, *args, **kwargs)
    return call


def app_data_dir() -> Path:
    override = os.environ.get("DVD_PLAYER_DATA_DIR")
    if override:
        return Path(override)
    return Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local" / "share")) / "dvd_player"


def subtitle_data_dir() -> Path:
    override = os.environ.get("DVD_PLAYER_DATA_DIR")
    if override:
        return Path(override) / "subtittle"
    return Path(__file__).resolve().parents[2] / "subtittle"


def setup_logging(root: Path) -> logging.Logger:
    logger = logging.getLogger("dvd_player")
    logger.setLevel(logging.INFO)
    if logger.handlers:
        return logger
    try:
        directory = root / "logs"
        directory.mkdir(parents=True, exist_ok=True)
        handler = RotatingFileHandler(directory / "application.log", maxBytes=2 * 1024 * 1024,
                                      backupCount=3, encoding="utf-8")
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
    except OSError:
        logger.addHandler(logging.NullHandler())
    return logger


@dataclass(frozen=True)
class CachedTrack:
    track_id: str
    language: str
    index: CueIndex


def key(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


class CacheStore:
    def __init__(self, root: Path, limit_bytes: int = 512 * 1024 * 1024):
        self.root = root.resolve()
        self.limit = limit_bytes
        self.lock = threading.RLock()
        self.media_names = {}

    def set_media_name(self, media_id: str, name: str):
        if not media_id:
            raise ValueError("DVD識別情報がありません。")
        safe_name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", name).strip(" ._")
        safe_name = safe_name[:80] or "DVD"
        reserved_names = {"CON", "PRN", "AUX", "NUL"}
        reserved_names.update(f"COM{i}" for i in range(1, 10))
        reserved_names.update(f"LPT{i}" for i in range(1, 10))
        if safe_name.upper().split(".", 1)[0] in reserved_names:
            safe_name = f"_{safe_name}"
        self.media_names[media_id] = safe_name

    def title_dir(self, media_id: str, title_id: int) -> Path:
        if type(title_id) is not int or title_id < 0:
            raise ValueError("タイトル番号が不正です。")
        media_name = self.media_names.get(media_id, f"DVD-{key(media_id)[:8]}")
        return self.root / media_name / key(media_id) / f"title-{title_id + 1:02d}"

    def load_tracks(self, media_id: str, title_id: int) -> list[CachedTrack]:
        tracks = []
        for manifest in sorted(self.title_dir(media_id, title_id).glob("*/manifest.json")):
            try:
                index, language = read_manifest(manifest, media_id, title_id)
                tracks.append(CachedTrack(manifest.parent.name, language, index))
                os.utime(manifest, None)
            except (OSError, ValueError, KeyError, TypeError):
                logging.getLogger("dvd_player").warning("CACHE_INVALID title=%s", title_id)
        return sorted(tracks, key=lambda track: (track.language, not bool(track.index.cues),
                      not all(c.text is not None for c in track.index.cues), track.track_id))

    @serialized
    def import_manifest(self, source: Path, media_id: str, title_id: int):
        index, language = read_manifest(source, media_id, title_id)
        data = json.loads(source.read_text(encoding="utf-8-sig"))
        # A content-based key keeps different tracks separate without trusting path components.
        digest = hashlib.sha256()
        digest.update(language.encode("ascii"))
        for cue in index.cues:
            digest.update(f"{cue.cue_id}:{cue.start_ms}:{cue.end_ms}".encode("utf-8"))
            if cue.text is not None:
                digest.update(cue.text.encode("utf-8"))
            else:
                with cue.image.open("rb") as stream:
                    for block in iter(lambda: stream.read(65536), b""):
                        digest.update(block)
        track_id = digest.hexdigest()
        destination = self.title_dir(media_id, title_id) / track_id
        warning = False
        try:
            if destination.exists():
                try:
                    cached, _ = read_manifest(destination / "manifest.json", media_id, title_id)
                    return CachedTrack(track_id, language, cached), False
                except (OSError, ValueError):
                    if not destination.resolve().is_relative_to(self.root):
                        raise OSError("invalid cache directory")
                    shutil.rmtree(destination)
            rows = [dict(cue_id=cue.cue_id, start_ms=cue.start_ms, end_ms=cue.end_ms,
                         **({"text": cue.text} if cue.text is not None else
                            {"image_path": f"images/{number:06}.png"})) for number, cue in enumerate(index.cues)]
            data.update(track_id=track_id, cues=rows)
            manifest_text = json.dumps(data)
            size = sum(cue.image.stat().st_size for cue in index.cues if cue.image) + len(manifest_text.encode("utf-8"))
            if size > self.limit:
                raise OSError("cache quota exceeded")
            destination.parent.mkdir(parents=True, exist_ok=True)
            self._make_room(size, destination.parent)
            if not destination.exists():
                with tempfile.TemporaryDirectory(prefix=".pending-", dir=destination.parent) as temp:
                    staging = Path(temp)
                    (staging / "images").mkdir()
                    for number, cue in enumerate(index.cues):
                        name = f"images/{number:06}.png"
                        if cue.image:
                            shutil.copyfile(cue.image, staging / name)
                    (staging / "manifest.json").write_text(manifest_text, encoding="utf-8")
                    staging.rename(destination)
                    # TemporaryDirectory tolerates the original path having been renamed.
            cached, _ = read_manifest(destination / "manifest.json", media_id, title_id)
            index = cached
        except OSError:
            warning = True
            logging.getLogger("dvd_player").warning("CACHE_WRITE_FAILED title=%s", title_id)
        return CachedTrack(track_id, language, index), warning

    def import_srt(self, source: Path, media_id: str, title_id: int, language: str):
        from dvd_player.subtitle_edit import parse_srt
        if language not in ("en", "ja"):
            raise ValueError("英語または日本語を選択してください。")
        index = parse_srt(source)
        data = dict(schema_version=1, media_id=media_id, title_id=title_id,
                    language=language, complete=True,
                    cues=[dict(cue_id=c.cue_id, start_ms=c.start_ms, end_ms=c.end_ms, text=c.text)
                          for c in index.cues])
        track_id = key(f"srt:{language}")
        text = json.dumps(data, ensure_ascii=False)
        size = len(text.encode("utf-8"))
        if size > 20 * 1024 * 1024:
            raise ValueError("テキスト字幕の保存データが大きすぎます。")
        warning = False
        with self.lock:
            try:
                title_directory = self.title_dir(media_id, title_id)
                directory = title_directory / track_id
                directory.mkdir(parents=True, exist_ok=True)
                manifest = directory / "manifest.json"
                old_size = manifest.stat().st_size if manifest.exists() else 0
                subtitle = title_directory / f"subtitles.{language}.srt"
                old_subtitle_size = subtitle.stat().st_size if subtitle.exists() else 0
                incoming = max(0, size - old_size) + max(0, source.stat().st_size - old_subtitle_size)
                self._make_room(incoming, title_directory)
                pending_manifest = directory / "manifest.pending"
                pending_manifest.write_text(text, encoding="utf-8")
                pending_manifest.replace(manifest)
                if source.resolve() != subtitle.resolve():
                    pending_subtitle = directory / f"subtitles.{language}.pending"
                    shutil.copyfile(source, pending_subtitle)
                    pending_subtitle.replace(subtitle)
            except OSError:
                logging.getLogger("dvd_player").warning("SRT_CACHE_WRITE_FAILED title=%s", title_id)
                warning = True
        return CachedTrack(track_id, language, index), warning

    @serialized
    def save_snapshot(self, source: Path, media_id: str, title_id: int):
        """Replace a stream's partial manifest atomically, retaining stable image paths."""
        index, language = read_manifest(source, media_id, title_id)
        data = json.loads(source.read_text(encoding="utf-8"))
        track_id = key(f"dvd:{language}:{data['track_id']}")
        destination = self.title_dir(media_id, title_id) / track_id
        destination.mkdir(parents=True, exist_ok=True)
        manifest = destination / "manifest.json"
        if manifest.exists() and not index.complete:
            try:
                previous, _ = read_manifest(manifest, media_id, title_id)
                if previous.complete or max((e for _, e in previous.coverage), default=0) >= max(
                        (e for _, e in index.coverage), default=0):
                    return CachedTrack(track_id, language, previous)
            except (ValueError, OSError):
                pass
        rows = [dict(cue_id=cue.cue_id, start_ms=cue.start_ms, end_ms=cue.end_ms,
                     image_path=f"images/{number:06}.png") for number, cue in enumerate(index.cues)]
        data.update(cues=rows)
        text = json.dumps(data)
        pending_images = [(cue.image, destination / row['image_path'])
                          for cue, row in zip(index.cues, rows) if not (destination / row['image_path']).exists()]
        manifest = destination / "manifest.json"
        old_size = manifest.stat().st_size if manifest.exists() else 0
        incoming = sum(image.stat().st_size for image, _ in pending_images) + max(0, len(text.encode()) - old_size)
        self._make_room(incoming, destination.parent)
        (destination / "images").mkdir(exist_ok=True)
        for image, target in pending_images:
            temporary = target.with_suffix(".pending")
            shutil.copyfile(image, temporary)
            temporary.replace(target)
        temporary = destination / "manifest.pending"
        temporary.write_text(text, encoding="utf-8")
        temporary.replace(manifest)
        cached, _ = read_manifest(manifest, media_id, title_id)
        return CachedTrack(track_id, language, cached)

    def language_map(self, media_id, title_id):
        path = self.title_dir(media_id, title_id) / "language_map.json"
        try:
            if path.stat().st_size > 65536:
                return {}
            data = json.loads(path.read_text(encoding="utf-8"))
            return {int(k): v for k, v in data.items() if str(k).isdigit() and v in ("en", "ja")}
        except (OSError, ValueError, AttributeError):
            return {}

    @serialized
    def save_language_map(self, media_id, title_id, mapping):
        if any(type(k) is not int or k < 0 or v not in ("en", "ja") for k, v in mapping.items()):
            raise ValueError("字幕の言語指定が不正です。")
        directory = self.title_dir(media_id, title_id)
        directory.mkdir(parents=True, exist_ok=True)
        temporary = directory / "language_map.pending"
        temporary.write_text(json.dumps(mapping), encoding="utf-8")
        temporary.replace(directory / "language_map.json")

    def _make_room(self, incoming: int, protected_title: Path):
        manifests = list(self.root.rglob("manifest.json"))
        entries = []
        total = 0
        titles = {manifest.parent.parent for manifest in manifests}
        for directory in titles:
            size = sum(file.stat().st_size for file in directory.rglob("*") if file.is_file())
            total += size
            entries.append((directory.stat().st_mtime, directory, size))
        for _, directory, size in sorted(entries):
            if total + incoming <= self.limit:
                break
            if directory != protected_title:
                resolved = directory.resolve()
                if not resolved.is_relative_to(self.root) or resolved == self.root:
                    raise OSError("invalid cache directory")
                shutil.rmtree(resolved)
                total -= size
        if total + incoming > self.limit:
            raise OSError("cache quota exceeded")
