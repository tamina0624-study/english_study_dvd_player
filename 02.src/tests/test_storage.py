import json
from pathlib import Path
import tempfile
import unittest

from dvd_player.storage import CacheStore


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.source = self.root / "source"
        self.source.mkdir()
        (self.source / "image.png").write_bytes(b"example-image")
        self.manifest = self.source / "manifest.json"
        self.data = dict(schema_version=1, media_id="dvd", title_id=0,
                         language="en", complete=True,
                         cues=[dict(cue_id="a", start_ms=0, end_ms=1000,
                                    image_path="image.png")])
        self.cache = CacheStore(self.root / "cache")

    def save(self):
        self.manifest.write_text(json.dumps(self.data), encoding="utf-8")
        return self.cache.import_manifest(self.manifest, self.data["media_id"], self.data["title_id"])

    def test_roundtrip_copies_images_and_reuses_cache(self):
        track, warning = self.save()
        self.assertFalse(warning)
        (self.source / "image.png").unlink()
        tracks = self.cache.load_tracks("dvd", 0)
        self.assertEqual(len(tracks), 1)
        self.assertEqual(tracks[0].track_id, track.track_id)
        self.assertEqual(tracks[0].index.cues[0].image.read_bytes(), b"example-image")
        self.assertEqual(self.cache.load_tracks("dvd", 1), [])

    def test_tracks_do_not_overwrite_each_other(self):
        self.save()
        self.data["cues"][0]["start_ms"] = 200
        self.save()
        self.assertEqual(len(self.cache.load_tracks("dvd", 0)), 2)

    def test_duplicate_import_reuses_same_directory(self):
        first, _ = self.save()
        second, _ = self.save()
        self.assertEqual(first.track_id, second.track_id)
        self.assertEqual(len(self.cache.load_tracks("dvd", 0)), 1)

    def test_quota_failure_keeps_source_available(self):
        self.cache.limit = 1
        track, warning = self.save()
        self.assertTrue(warning)
        self.assertEqual(track.index.cues[0].image.parent, self.source)
        self.assertEqual(self.cache.load_tracks("dvd", 0), [])

    def test_corrupt_cache_is_not_loaded(self):
        track, _ = self.save()
        manifest = track.index.cues[0].image.parent.parent / "manifest.json"
        manifest.write_text("broken", encoding="utf-8")
        self.assertEqual(self.cache.load_tracks("dvd", 0), [])
        repaired, warning = self.save()
        self.assertFalse(warning)
        self.assertEqual(repaired.track_id, track.track_id)

    def test_lru_evicts_other_title_but_protects_current(self):
        self.save()
        old_size = sum(p.stat().st_size for p in self.cache.root.rglob("*") if p.is_file())
        self.data["title_id"] = 1
        self.manifest.write_text(json.dumps(self.data), encoding="utf-8")
        incoming = self.manifest.stat().st_size + (self.source / "image.png").stat().st_size
        self.cache.limit = max(old_size, incoming) + 200
        self.save()
        self.assertEqual(self.cache.load_tracks("dvd", 0), [])
        self.assertEqual(len(self.cache.load_tracks("dvd", 1)), 1)


if __name__ == "__main__":
    unittest.main()
