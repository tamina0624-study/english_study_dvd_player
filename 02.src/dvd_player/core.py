"""Pure domain operations, independent of Qt and VLC."""
from bisect import bisect_right
from dataclasses import dataclass
import json
from pathlib import Path
import time


def timestamp(ms: int | None) -> str:
    if ms is None or ms < 0:
        return "--:--"
    seconds = ms // 1000
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    return f"{hours:02}:{minutes:02}:{seconds:02}" if hours else f"{minutes:02}:{seconds:02}"


@dataclass(frozen=True)
class Cue:
    cue_id: str
    start_ms: int
    end_ms: int
    image: Path


class CueIndex:
    def __init__(self, cues=()):
        self.cues = sorted(cues, key=lambda c: (c.start_ms, c.end_ms, c.cue_id))
        self.starts = [c.start_ms for c in self.cues]
        self.max_ends = []
        end = 0
        for cue in self.cues:
            end = max(end, cue.end_ms)
            self.max_ends.append(end)

    def active(self, ms: int) -> list[int]:
        i = bisect_right(self.starts, ms) - 1
        result = []
        while i >= 0 and self.max_ends[i] > ms:
            if self.cues[i].end_ms > ms:
                result.append(i)
            i -= 1
        return list(reversed(result))


@dataclass
class SeekCoordinator:
    target: int | None = None
    sent: int | None = None
    started: float = 0
    resume: bool = False

    def request(self, target: int, resume: bool):
        if self.target is None:
            self.resume = resume
        self.target = max(0, target)

    def rewind(self, actual: int, resume: bool):
        self.request((self.target if self.target is not None else actual) - 2000, resume)

    def next_command(self, actual: int, now: float | None = None):
        now = time.monotonic() if now is None else now
        if self.target is None:
            return None
        if self.sent is not None:
            if now - self.started > 5:
                self.clear()
                raise TimeoutError("再生位置の変更を確認できませんでした。")
            if abs(actual - self.sent) > 500:
                return None
            self.sent = None
            if abs(actual - self.target) <= 500:
                self.target = None
                return None
        self.sent = self.target
        self.started = now
        return self.sent

    def clear(self):
        self.target = self.sent = None


def read_manifest(path: Path, media_id: str, title_id: int) -> tuple[CueIndex, str]:
    """Validate a prepared image subtitle manifest before displaying it."""
    if path.stat().st_size > 20 * 1024 * 1024:
        raise ValueError("字幕情報ファイルが大きすぎます。")
    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict) or type(data.get("schema_version")) is not int or data.get("schema_version") != 1:
        raise ValueError("字幕データの形式が未対応です。")
    if data.get("media_id") != media_id or type(data.get("title_id")) is not int or data.get("title_id") != title_id:
        raise ValueError("DVDまたはタイトルが字幕データと一致しません。")
    language = data.get("language")
    if language not in ("en", "ja"):
        raise ValueError("字幕の言語はenまたはjaを指定してください。")
    if data.get("complete") is not True:
        raise ValueError("この版では取得完了済みの字幕データのみ読み込めます。")
    rows = data.get("cues")
    if not isinstance(rows, list) or len(rows) > 100000:
        raise ValueError("字幕の件数が不正です。")
    root = path.parent.resolve()
    cues, ids = [], set()
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("字幕行が不正です。")
        key, start, end = row.get("cue_id"), row.get("start_ms"), row.get("end_ms")
        if not isinstance(key, str) or not key or key in ids:
            raise ValueError("字幕IDが不正または重複しています。")
        if type(start) is not int or type(end) is not int or not 0 <= start < end:
            raise ValueError("字幕の時刻が不正です。")
        relative = row.get("image_path")
        if not isinstance(relative, str) or Path(relative).is_absolute():
            raise ValueError("字幕画像のパスが不正です。")
        image = (root / relative).resolve()
        if not image.is_relative_to(root) or not image.is_file():
            raise ValueError("字幕画像が見つからないか、保存範囲外です。")
        ids.add(key)
        cues.append(Cue(key, start, end, image))
    return CueIndex(cues), language
