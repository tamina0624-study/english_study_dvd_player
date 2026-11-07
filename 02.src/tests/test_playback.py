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


if __name__ == "__main__":
    unittest.main()
