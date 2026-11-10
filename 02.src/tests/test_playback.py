from types import SimpleNamespace
import unittest
from unittest.mock import MagicMock

from dvd_player.playback import Player


class PlaybackAdapterTests(unittest.TestCase):
    def adapter(self):
        adapter = Player.__new__(Player)
        adapter.player = MagicMock()
        adapter.player.play.return_value = 0
        adapter.instance = MagicMock()
        adapter.media = None
        return adapter

    def test_dvd_uri_uses_fragment_for_real_title(self):
        adapter = self.adapter()
        adapter.open("D:\\", 0)
        adapter.instance.media_new.assert_called_once_with("dvd:///D:/#1")
        adapter.player.play.assert_called_once()

    def test_title_list_excludes_menu_and_preserves_dvd_numbers(self):
        adapter = self.adapter()
        adapter.player.get_full_title_descriptions.return_value = [
            SimpleNamespace(duration=0, flags=3),
            SimpleNamespace(duration=50000, flags=0),
            SimpleNamespace(duration=25000, flags=0),
        ]
        self.assertEqual(adapter.titles(), [(0, 50000), (1, 25000)])

    def test_chapter_navigation_preserves_playback_state(self):
        for playing in (False, True):
            with self.subTest(playing=playing):
                adapter = self.adapter()
                p = adapter.player
                p.get_chapter.return_value = 0
                p.get_chapter_count.return_value = 3
                p.is_playing.return_value = playing
                adapter.change_chapter(1)
                p.set_chapter.assert_called_once_with(1)
                p.set_time.assert_not_called()
                p.get_full_chapter_descriptions.assert_not_called()
                if playing:
                    p.set_pause.assert_not_called()
                else:
                    p.set_pause.assert_called_once_with(1)

    def test_chapter_out_of_range_does_not_change_playback(self):
        adapter = self.adapter()
        adapter.player.get_chapter.return_value = 0
        adapter.player.get_chapter_count.return_value = 2
        adapter.change_chapter(-1)
        adapter.player.set_chapter.assert_not_called()
        adapter.player.play.assert_not_called()

    def test_title_preparation_does_not_seek_paused_dvd(self):
        adapter = self.adapter()
        adapter.prepare(70, False)
        adapter.player.set_pause.assert_called_once_with(1)
        adapter.player.audio_set_volume.assert_called_once_with(70)
        adapter.player.set_time.assert_not_called()


if __name__ == "__main__":
    unittest.main()
