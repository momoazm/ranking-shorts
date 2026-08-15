import contextlib
import io
import json
import sys
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))

import build_ranking_video  # noqa: E402
import find_streamer_clips  # noqa: E402
import rank_clips  # noqa: E402
import rank_autopost  # noqa: E402
import compare_streamer_formats  # noqa: E402


class StreamerPipelineGuardsTest(unittest.TestCase):
    def test_download_matrix_has_direct_and_warp_legs_without_non_streamer_clients(self):
        routes = {(tuple(client or ()), use_proxy)
                  for client, _fmt, use_proxy in build_ranking_video._DL_ATTEMPTS}
        self.assertEqual(len(routes), 8)
        self.assertIn(((), False), routes)
        self.assertIn(((), True), routes)
        self.assertIn((("web_safari",), False), routes)
        self.assertIn((("web_safari",), True), routes)
        self.assertIn((("tv",), False), routes)
        self.assertIn((("tv",), True), routes)
        self.assertNotIn((("android",), True), routes)
        self.assertNotIn((("ios",), False), routes)

    def test_streamer_identity_gate_is_strict(self):
        self.assertTrue(find_streamer_clips.streamer_signal("Kai Cenat funniest reaction", "Kai Cenat"))
        self.assertTrue(find_streamer_clips.streamer_signal("Twitch streamer rage", "Creator Clips"))
        self.assertFalse(find_streamer_clips.streamer_signal("funny family fails", "Random Channel"))

    def test_ranker_keeps_five_streamer_rows_and_metadata_order(self):
        candidates = [
            {"id": f"clip-{index}", "title": f"Kai Cenat moment {index}",
             "url": f"https://www.youtube.com/watch?v=clip-{index}", "channel": "Kai Cenat",
             "uploader": "Kai Cenat", "source": "youtube", "source_feed": "youtube-search",
             "content_type": "streamer_clip", "streamer_identity": "Kai Cenat",
             "content_policy": "streamer-only"}
            for index in range(5)
        ]
        raw = [{"candidate_index": index, "label": f"Moment {index}"} for index in range(5)]
        ranked = rank_clips.clean_ranking_entries(raw, candidates)
        self.assertEqual(len(ranked), 5)
        self.assertEqual([row["rank"] for row in ranked], [5, 4, 3, 2, 1])
        self.assertEqual([row["id"] for row in ranked], [f"clip-{i}" for i in range(5)])
        self.assertTrue(all(row["content_type"] == "streamer_clip" for row in ranked))
        self.assertTrue(all(row["content_policy"] == "streamer-only" for row in ranked))
        self.assertTrue(all(row["streamer_identity"] == row["channel"] for row in ranked))

    def test_source_starvation_returns_before_caption_or_delivery(self):
        candidates = [
            {"id": f"clip-{index}", "title": "Kai Cenat funny moment", "content_type": "streamer_clip",
             "streamer_identity": "Kai Cenat", "content_policy": "streamer-only"}
            for index in range(5)
        ]
        calls = []

        def fake_run_tool(name, _args):
            calls.append(name)
            if name == "rank_topic.py":
                return {"genre": "streamer", "title": "Streamer Moments", "hook": "Top five"}
            raise AssertionError(f"unexpected raising tool: {name}")

        def fake_run_tool_safe(name, _args):
            calls.append(name)
            if name == "find_streamer_clips.py":
                (ROOT / rank_autopost.CANDS).parent.mkdir(parents=True, exist_ok=True)
                (ROOT / rank_autopost.CANDS).write_text(
                    json.dumps({"source": "youtube", "genre": "streamer",
                                "content_policy": "streamer-only", "candidates": candidates}),
                    encoding="utf-8",
                )
                return {"count": 5, "candidates": candidates}, None
            if name == "rank_clips.py":
                return {"count": 5}, None
            if name == "refine_title.py":
                return {"title": "Streamer Moments", "hook": "Top five"}, None
            if name == "build_ranking_video.py":
                err = "build_ranking_video.py failed: Only 0 usable clips -- need >=5. YouTube download failed"
                return {"error": err}, err
            raise AssertionError(f"unexpected safe tool: {name}")

        argv = ["rank_autopost.py", "--no-upload", "--format", "ranking", "--force-genre", "streamer",
                "--platforms", "youtube,instagram"]
        captured = io.StringIO()
        try:
            with mock.patch.object(sys, "argv", argv), \
                    mock.patch.dict("os.environ", {"RANKING_SOURCE": "streamer", "NO_SOURCE_OK": "1"}, clear=False), \
                    mock.patch.object(rank_autopost, "load_env", lambda: None), \
                    mock.patch.object(rank_autopost, "run_tool", side_effect=fake_run_tool), \
                    mock.patch.object(rank_autopost, "run_tool_safe", side_effect=fake_run_tool_safe), \
                    contextlib.redirect_stdout(captured):
                rank_autopost.main()
        finally:
            try:
                (ROOT / rank_autopost.CANDS).unlink()
            except FileNotFoundError:
                pass

        result = json.loads(captured.getvalue().strip())
        self.assertEqual(result["status"], "no_source")
        self.assertEqual(result["content_policy"], "streamer-only")
        self.assertEqual(result["candidate_count"], 5)
        self.assertNotIn("build_captions.py", calls)
        self.assertNotIn("host_public.py", calls)
        self.assertNotIn("upload_youtube.py", calls)
        self.assertNotIn("upload_instagram.py", calls)

    def test_unrelated_build_error_is_not_source_starvation(self):
        self.assertFalse(rank_autopost._is_streamer_source_starvation(
            "configuration error: ffmpeg missing"
        ))
        self.assertTrue(rank_autopost._is_streamer_source_starvation(
            "Only 3 usable clips -- need >=5. download failed"
        ))

    def test_auto_format_defaults_to_standalone_and_keeps_ranked_control(self):
        selected, state = rank_autopost.choose_format("auto", no_upload=True)
        self.assertEqual(selected, "standalone")
        self.assertIsInstance(state, dict)
        selected_ranked, _ = rank_autopost.choose_format("ranking", no_upload=True)
        self.assertEqual(selected_ranked, "ranking")

    def test_standalone_download_failure_is_source_starvation_only(self):
        self.assertTrue(rank_autopost._is_streamer_clip_download_failure(
            "build_clip.py failed: download failed: bot check"))
        self.assertFalse(rank_autopost._is_streamer_clip_download_failure(
            "build_clip.py failed: overlay burn failed"))

    def test_format_comparator_requires_clear_mature_winner(self):
        stats = {
            "standalone": [{"views": 200, "engagement_rate": 0.12}] * 3,
            "ranking": [{"views": 100, "engagement_rate": 0.10}] * 3,
        }
        winner, _ = compare_streamer_formats.decide(stats)
        self.assertEqual(winner, "standalone")
        stats["standalone"] = [{"views": 110, "engagement_rate": 0.12}] * 3
        winner, reason = compare_streamer_formats.decide(stats)
        self.assertIsNone(winner)
        self.assertIn("no clear winner", reason)

    def test_streamer_signal_prefers_concrete_conflict_over_generic_gameplay(self):
        concrete = rank_clips.streamer_signal_score({
            "title": "Kai gets called out over a cringe chat question",
            "channel": "Kai Cenat", "duration": 32,
        })
        generic = rank_clips.streamer_signal_score({
            "title": "Funny moments compilation gameplay",
            "channel": "Creator Clips", "duration": 90,
        })
        self.assertGreater(concrete, generic)

    def test_format_comparator_keeps_retention_as_a_guardrail(self):
        stats = {
            "standalone": [{"views": 200, "engagement_rate": 0.12,
                            "watch_completion_ratio": 0.10}] * 3,
            "ranking": [{"views": 100, "engagement_rate": 0.10,
                         "watch_completion_ratio": 0.20}] * 3,
        }
        winner, reason = compare_streamer_formats.decide(stats)
        self.assertIsNone(winner)
        self.assertIn("watch completion", reason)


if __name__ == "__main__":
    unittest.main()
