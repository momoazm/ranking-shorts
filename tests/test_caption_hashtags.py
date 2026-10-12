import contextlib
import io
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))

import build_captions  # noqa: E402
import rank_autopost  # noqa: E402


class CaptionHashtagsTest(unittest.TestCase):
    """R3 (2026-10 audit): the generic ranking CORE was merged BEFORE the sharktank story
    tags while Instagram keeps only 5 hashtags, so every pitch-show post shipped
    #ranking #top5 #countdown #funnyfails #fails. These two tests pin the fix."""

    def _captions(self, story, core=None):
        with tempfile.TemporaryDirectory() as tmp:
            story_path = Path(tmp) / "story.json"
            out_path = Path(tmp) / "captions.json"
            story_path.write_text(json.dumps(story), encoding="utf-8")
            argv = ["build_captions.py", "--story", str(story_path), "--out", str(out_path)]
            if core is not None:
                argv += ["--core", core]
            with mock.patch.object(sys, "argv", argv), contextlib.redirect_stdout(io.StringIO()):
                build_captions.main()
            return json.loads(out_path.read_text(encoding="utf-8"))

    @staticmethod
    def _ig_tags(meta):
        return re.findall(r"#([a-z0-9]+)", (meta["instagram"]["caption"] or "").lower())

    def test_sharktank_caption_first_five_ig_tags_are_niche_not_ranking_core(self):
        story = {
            "title": "BarMate's Self-Pouring Pint Impresses the Dragons",
            "description": "BarMate's Self-Pouring Pint Impresses the Dragons",
            # Exactly what rank_autopost writes for a sharktank standalone post: title
            # words first, then the show/business seed tags.
            "tags": ["barmate", "selfpouring", "pint", "impresses", "dragons",
                     "sharktank", "sharktankus", "startup", "investment", "shorts"],
        }
        meta = self._captions(story, rank_autopost.SHARKTANK_CORE)
        ig = self._ig_tags(meta)
        self.assertEqual(len(ig), 5, f"Instagram keeps exactly 5: {ig}")
        for niche in ("sharktank", "startup", "investment", "business", "pitch"):
            self.assertIn(niche, ig, f"niche tag missing from the IG cap: {ig}")
        self.assertNotIn("funnyfails", ig)
        self.assertNotIn("countdown", ig)
        self.assertNotIn("ranking", ig)

    def test_ranking_and_streamer_captions_are_unchanged_without_core(self):
        ranking = self._captions({
            "title": "Top 5 Fails of the Week",
            "description": "The funniest countdown of the week",
            "tags": ["fails", "countdown", "week", "ranking", "top5", "shorts"],
        })
        self.assertEqual(self._ig_tags(ranking)[:5],
                         ["ranking", "top5", "countdown", "funnyfails", "fails"])
        streamer = self._captions({
            "title": "Kai Cenat Loses It On Stream",
            "description": "Live streamer moment",
            "tags": ["kai", "cenat", "loses", "stream", "streamer", "streamerclips",
                     "liveclip", "shorts"],
        })
        self.assertEqual(self._ig_tags(streamer)[:5],
                         ["ranking", "top5", "countdown", "funnyfails", "fails"])
        # The orchestrator only passes --core for the sharktank genre.
        self.assertTrue(rank_autopost.SHARKTANK_CORE)
        self.assertNotIn("funnyfails", rank_autopost.SHARKTANK_CORE)


if __name__ == "__main__":
    unittest.main()
