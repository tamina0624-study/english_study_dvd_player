"""Local, bounded subtitle cache and privacy-conscious application logging."""
from dataclasses import dataclass
import hashlib
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import shutil
import tempfile

from dvd_player.core import CueIndex, read_manifest


def app_data_dir() -> Path:
    override = os.environ.get("DVD_PLAYER_DATA_DIR")
    if override:
        return Path(override)
    return Path(os.environ.get("LOCALAPPDATA", Path.home() / ".local" / "share")) / "dvd_player"


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

    def title_dir(self, media_id: str, title_id: int) -> Path:
        if type(title_id) is not int or title_id < 0:
            raise ValueError("タイトル番号が不正です。")
        return self.root / key(media_id) / str(title_id)

    def load_tracks(self, media_id: str, title_id: int) -> list[CachedTrack]:
        tracks = []
        for manifest in sorted(self.title_dir(media_id, title_id).glob("*/manifest.json")):
            try:
                index, language = read_manifest(manifest, media_id, title_id)
                tracks.append(CachedTrack(manifest.parent.name, language, index))
                os.utime(manifest, None)
            except (OSError, ValueError, KeyError, TypeError):
                logging.getLogger("dvd_player").warning("CACHE_INVALID title=%s", title_id)
        return tracks

    def import_manifest(self, source: Path, media_id: str, title_id: int):
        index, language = read_manifest(source, media_id, title_id)
        data = json.loads(source.read_text(encoding="utf-8-sig"))
        # A content-based key keeps different tracks separate without trusting path components.
        digest = hashlib.sha256()
        digest.update(language.encode("ascii"))
        for cue in index.cues:
            digest.update(f"{cue.cue_id}:{cue.start_ms}:{cue.end_ms}".encode("utf-8"))
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
                         image_path=f"images/{number:06}.png") for number, cue in enumerate(index.cues)]
            data.update(track_id=track_id, cues=rows)
            manifest_text = json.dumps(data)
            size = sum(cue.image.stat().st_size for cue in index.cues) + len(manifest_text.encode("utf-8"))
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

    def _make_room(self, incoming: int, protected_title: Path):
        manifests = list(self.root.glob("*/*/*/manifest.json"))
        entries = []
        total = 0
        for manifest in manifests:
            size = sum(file.stat().st_size for file in manifest.parent.rglob("*") if file.is_file())
            total += size
            entries.append((manifest.stat().st_mtime, manifest.parent, size))
        for _, directory, size in sorted(entries):
            if total + incoming <= self.limit:
                break
            if directory.parent != protected_title:
                # Directories originate from the fixed cache hierarchy, never a manifest path.
                resolved = directory.resolve()
                if not resolved.is_relative_to(self.root) or resolved == self.root:
                    raise OSError("invalid cache directory")
                shutil.rmtree(resolved)
                total -= size
        if total + incoming > self.limit:
            raise OSError("cache quota exceeded")
