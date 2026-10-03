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
import build_clip  # noqa: E402
import find_streamer_clips  # noqa: E402
import rank_clips  # noqa: E402
import rank_autopost  # noqa: E402
import compare_streamer_formats  # noqa: E402
import find_sharktank_parts  # noqa: E402


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

    def test_audio_policy_keeps_native_pitch_and_payoff_first_hook(self):
        self.assertEqual(build_ranking_video.DEFAULT_MUSIC_PITCH, 1.0)
        self.assertLessEqual(build_ranking_video.DEFAULT_MUSIC_VOLUME, 0.10)
        self.assertIn("PAYOFF", build_ranking_video.DEFAULT_TEASER_TEXT)

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

    def test_format_slot_advances_only_after_confirmed_upload(self):
        state = {"run_index": 4, "runs": [], "winner": None}
        path = ROOT / ".tmp" / "test_format_state.json"
        with mock.patch.object(rank_autopost, "load_json", return_value=state), \
             mock.patch.object(rank_autopost, "FORMAT_STATE", ".tmp/test_format_state.json"):
            try:
                selected, reserved = rank_autopost.choose_format("auto", no_upload=False)
                self.assertEqual(selected, "ranking")
                rank_autopost.save_format_state(reserved, "ranking", status="delivery_failed")
                failed = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(failed["run_index"], 4)
                self.assertEqual(failed["pending_format"], "ranking")
                rank_autopost.save_format_state(failed, "ranking", status="uploaded")
                uploaded = json.loads(path.read_text(encoding="utf-8"))
                self.assertEqual(uploaded["run_index"], 5)
                self.assertNotIn("pending_format", uploaded)
            finally:
                path.unlink(missing_ok=True)

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

    # --- Scheduled download-wall handling ----------------------------------------------------
    # 2026-10-02 run 36979089034: NO_SOURCE_OK=1 was set, every one of the 5 standalone
    # candidates was bot-walled, and the run still went red because the standalone
    # `for...else` raised past the NO_SOURCE_OK escape hatch. These two tests pin both
    # sides of that contract.
    def _run_standalone_all_walled(self, no_source_ok):
        entries = [
            {"rank": index + 1, "content_type": "streamer_clip",
             "content_policy": "streamer-only", "streamer_identity": "Kai Cenat",
             "channel": "Kai Cenat", "url": f"https://www.youtube.com/watch?v=clip-{index}",
             "title": f"Kai Cenat moment {index}"}
            for index in range(5)
        ]
        candidates = [dict(entry, id=f"clip-{index}", source="youtube",
                           source_feed="youtube-search", uploader="Kai Cenat")
                      for index, entry in enumerate(entries)]
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
                                "content_policy": "streamer-only",
                                "candidates": candidates}), encoding="utf-8")
                return {"count": 5, "candidates": candidates}, None
            if name == "rank_clips.py":
                (ROOT / rank_autopost.RANKED).parent.mkdir(parents=True, exist_ok=True)
                (ROOT / rank_autopost.RANKED).write_text(
                    json.dumps({"count": 5, "entries": entries}), encoding="utf-8")
                return {"count": 5, "entries": entries}, None
            if name == "refine_title.py":
                return {"title": "Streamer Moments", "hook": "Top five"}, None
            if name == "build_clip.py":
                return None, ("build_clip.py failed: download failed: all YouTube download "
                              "routes failed (no cookies.txt in play)")
            raise AssertionError(f"unexpected safe tool: {name}")

        argv = ["rank_autopost.py", "--no-upload", "--format", "standalone",
                "--force-genre", "streamer", "--platforms", "youtube,instagram"]
        ranked_backup = None
        ranked_path = ROOT / rank_autopost.RANKED
        if ranked_path.is_file():
            ranked_backup = ranked_path.read_bytes()
        captured = io.StringIO()
        try:
            with mock.patch.object(sys, "argv", argv), \
                    mock.patch.dict("os.environ", {"RANKING_SOURCE": "streamer",
                                                   "NO_SOURCE_OK": no_source_ok}, clear=False), \
                    mock.patch.object(rank_autopost, "load_env", lambda: None), \
                    mock.patch.object(rank_autopost, "run_tool", side_effect=fake_run_tool), \
                    mock.patch.object(rank_autopost, "run_tool_safe", side_effect=fake_run_tool_safe), \
                    contextlib.redirect_stdout(captured):
                rank_autopost.main()
        finally:
            (ROOT / rank_autopost.CANDS).unlink(missing_ok=True)
            if ranked_backup is not None:
                ranked_path.write_bytes(ranked_backup)
            else:
                ranked_path.unlink(missing_ok=True)
        return captured.getvalue().strip(), calls

    def test_scheduled_standalone_download_wall_is_clean_no_post(self):
        out, calls = self._run_standalone_all_walled("1")
        result = json.loads(out)
        self.assertEqual(result["status"], "no_source")
        self.assertEqual(result["content_policy"], "streamer-only")
        self.assertEqual(result["format"], "standalone")
        self.assertIn("download failed for all 5 verified standalone candidates", result["detail"])
        for tool in ("host_public.py", "upload_youtube.py", "upload_instagram.py",
                     "prepare_upload_media.py"):
            self.assertNotIn(tool, calls)

    def test_publish_standalone_download_wall_still_fails_loudly(self):
        with self.assertRaises(RuntimeError) as ctx:
            self._run_standalone_all_walled("0")
        self.assertIn("download failed for all 5 verified standalone candidates", str(ctx.exception))

    def test_instagram_poll_ceiling_clears_transcode_retry(self):
        import upload_instagram  # argparse lives in build_parser(); import is side-effect free
        default_poll = upload_instagram.build_parser().parse_args(
            ["--video-url", "https://example.com/v.mp4"]).poll_timeout
        self.assertGreaterEqual(default_poll, 420,
                                "Instagram's self-retry transcode outlived the old 180s poll")
        # The child must outlive its own poll window (create-call backoff + poll budget).
        self.assertGreater(rank_autopost.TOOL_TIMEOUTS["upload_instagram.py"], default_poll + 60)


class SharktankPartsGuardsTest(unittest.TestCase):
    # prepare_upload_media.py rejects any media with `not (0 < duration < 60)`, so a part may
    # NEVER be exactly 60.0s: a full 600s source needs 11 parts, and a real 9:47 upload gives
    # the 10 near-one-minute parts the channel format asks for.
    def test_ten_minute_video_splits_into_ten_near_one_minute_parts(self):
        parts = find_sharktank_parts.split_parts(587.0)   # the real newest upload (9:47)
        self.assertEqual(len(parts), 10)
        self.assertTrue(all(0 < round(end - start, 2) < 60.0 for start, end in parts))
        self.assertAlmostEqual(parts[0][0], 0.0)
        self.assertAlmostEqual(parts[-1][1], 587.0)

    def test_exact_six_hundred_seconds_never_emits_a_sixty_second_part(self):
        parts = find_sharktank_parts.split_parts(600.0)
        self.assertEqual(len(parts), 11)
        self.assertTrue(all(0 < round(end - start, 2) < 60.0 for start, end in parts))
        self.assertAlmostEqual(parts[-1][1], 600.0)

    def test_even_multiples_never_gain_a_sliver_tail(self):
        self.assertEqual(len(find_sharktank_parts.split_parts(599.0)), 11)
        self.assertEqual(len(find_sharktank_parts.split_parts(120.0)), 3)
        sizes = [round(e - s, 2) for s, e in find_sharktank_parts.split_parts(61.0)]
        self.assertEqual(sizes, [30.5, 30.5])

    def test_short_and_bad_durations_are_rejected(self):
        self.assertEqual(find_sharktank_parts.split_parts(59.0), [(0.0, 59.0)])
        self.assertIsNone(find_sharktank_parts.split_parts(0))
        self.assertIsNone(find_sharktank_parts.split_parts(None))
        self.assertIsNone(find_sharktank_parts.split_parts(3600.0))  # hour-long: cap guard

    def test_caller_cannot_ask_for_an_over_limit_part(self):
        parts = find_sharktank_parts.split_parts(600.0, max_part_secs=300.0, max_parts=20)
        self.assertTrue(all(round(end - start, 2) <= find_sharktank_parts.MAX_SOURCE_SECS
                            for start, end in parts))

    def test_candidate_carries_the_part_contract(self):
        entry = {"id": "VID123", "title": "Startup Pitches",
                 "webpage_url": "https://www.youtube.com/watch?v=VID123",
                 "channel": "Shark Tank Global"}
        parts = find_sharktank_parts.split_parts(587.0)
        start, end = parts[2]
        cand = find_sharktank_parts.build_candidate(
            entry, parts, 3, start, end, "https://www.youtube.com/@SharkTankGlobal/videos")
        self.assertEqual(cand["id"], "VID123#3")
        self.assertEqual(cand["part_label"], "(Part 3/10)")
        self.assertIn("(Part 3/10)", cand["title"])
        self.assertEqual((cand["start"], cand["end"]), (start, end))
        self.assertLess(cand["duration"], 60.0)
        self.assertEqual(cand["content_type"], "sharktank_part")
        self.assertEqual(cand["content_policy"], "sharktank-only")

    def test_show_tag_keeps_the_hook_inside_clean_title_cap(self):
        # Two live runs showed the hook losing words to clean_title's 62-char cut: a 19-char
        # channel prefix cost "Kevin" (37115177398) and a 14-char prefix cost "Dragons"
        # (37117223221). The show therefore rides in the part label, which is appended AFTER
        # cleaning, so hook + part number + show all fit inside YouTube's 100-char title.
        entry = {"source_feed": "https://www.youtube.com/@SharkTankGlobal/videos",
                 "channel": "Shark Tank Global",
                 "source_title": ("The Foster Sisters Battle It Out With Kevin!? | "
                                  "Shark Tank US | Shark Tank Global"),
                 "part_label": "(Part 1/10)"}
        tag = rank_autopost.show_tag(entry)
        self.assertEqual(tag, "Shark Tank")
        cleaned = build_clip.clean_title(entry["source_title"])
        final = f"{cleaned} (Part 1/10) | {tag}".strip()
        self.assertTrue(cleaned.endswith("Kevin"), f"hook truncated: {cleaned!r}")
        self.assertLessEqual(len(cleaned), 62, "clean_title cap itself must hold the hook")
        self.assertIn("Shark Tank", final)
        self.assertLessEqual(len(final), 100, "YouTube title limit")
        # Unknown/long channel names must still fit, and the tag is never empty.
        self.assertLessEqual(
            len(rank_autopost.show_tag({"channel": "Shark Tank Australia (Official)"})), 14)
        self.assertEqual(rank_autopost.show_tag({"channel": "Dragons' Den"}), "Dragons' Den")
        self.assertTrue(rank_autopost.show_tag({}))

    def test_source_hook_picks_the_hook_in_both_title_orders(self):
        # Real feed shapes observed 2026-10-03. AU publishes "Show | Hook", so taking the
        # first segment burned "Shark Tank Australia (Part 1/8) | Shark Tank AU" -- a title
        # with no reason to click (run 37117676301).
        global_entry = {
            "channel": "Shark Tank Global",
            "source_feed": "https://www.youtube.com/@SharkTankGlobal/videos",
            "source_title": ("The Foster Sisters Battle It Out With Kevin!? | "
                             "Shark Tank US | Shark Tank Global"),
        }
        au_entry = {
            "channel": "Shark Tank Australia",
            "source_feed": "https://www.youtube.com/@SharkTankAustralia/videos",
            "source_title": ("Shark Tank Australia | Entrepreneur Enters The Tank Without "
                             "A Product... Only A Crazy Idea"),
        }
        dragons_entry = {
            "channel": "Dragons' Den",
            "source_feed": "https://www.youtube.com/@DragonsDenGlobal/videos",
            "source_title": "BarMate\u2019s Self-Pouring Pint Impresses the Dragons | Dragons\u2019 Den",
        }
        self.assertEqual(
            rank_autopost.source_hook(global_entry),
            "The Foster Sisters Battle It Out With Kevin!?")
        self.assertEqual(
            rank_autopost.source_hook(au_entry),
            "Entrepreneur Enters The Tank Without A Product...")
        self.assertEqual(
            rank_autopost.source_hook(dragons_entry),
            "BarMate\u2019s Self-Pouring Pint Impresses the Dragons")
        # The hook must survive clean_title, and the burned title must stay under 100.
        for entry, show, first_word in (
                (global_entry, "Shark Tank", "the foster"),
                (au_entry, "Shark Tank AU", "entrepreneur"),
                (dragons_entry, "Dragons' Den", "barmate")):
            cleaned = build_clip.clean_title(rank_autopost.source_hook(entry))
            burned = f"{cleaned} (Part 1/8) | {show}"
            self.assertTrue(cleaned.lower().startswith(first_word),
                            f"hook lost: {burned!r}")
            self.assertLessEqual(len(burned), 100, burned)
        # A short hook must still win when the show segment is longer than it.
        self.assertEqual(
            rank_autopost.source_hook({"channel": "Shark Tank Global",
                                       "source_title": "Deal | Shark Tank Global"}),
            "Deal")
        # Fallback path: no source_title, and the label must not be doubled up.
        self.assertEqual(
            rank_autopost.source_hook({"channel": "Shark Tank Global",
                                       "title": "Big Win (Part 1/8)"}), "Big Win")
        # No separators at all: hand the whole title straight through.
        self.assertEqual(rank_autopost.source_hook({"source_title": "One Line Hook"}),
                         "One Line Hook")

    def test_default_rotation_covers_four_verified_pitch_shows(self):
        feeds = find_sharktank_parts.DEFAULT_CHANNELS
        self.assertGreaterEqual(len(feeds), 4)
        blob = ",".join(feeds)
        self.assertIn("SharkTankGlobal", blob)
        self.assertTrue(any("dragon" in feed.lower() for feed in feeds))
        # The dead handle probed on 2026-10-03 (404) must never come back.
        self.assertNotIn("@dragonsden/videos", blob)

    def _run_finder(self, tmp, entries, used, rotation_offset=None, history_used=None):
        history = str(Path(tmp) / "used.json")
        Path(history).write_text(json.dumps({"used": history_used or used}), encoding="utf-8")
        rotation = str(Path(tmp) / "rotation.json")
        if rotation_offset is not None:
            Path(rotation).write_text(json.dumps({"offset": rotation_offset}), encoding="utf-8")
        out = str(Path(tmp) / "cands.json")
        with mock.patch.object(find_sharktank_parts, "search",
                               side_effect=lambda feed, n: entries[feed]), \
             mock.patch.object(find_sharktank_parts, "probe_duration",
                               side_effect=lambda entry: entry.get("duration")), \
             mock.patch("sys.argv", ["find_sharktank_parts.py",
                                     "--channel", ",".join(entries.keys()),
                                     "--history", history, "--rotation", rotation,
                                     "--out", out]):
            find_sharktank_parts.main()
        return json.loads(Path(out).read_text(encoding="utf-8")), rotation

    def test_main_rotates_to_second_feed_when_first_is_exhausted(self):
        import tempfile
        entries = {
            "https://www.youtube.com/@SharkTankGlobal/videos": [
                {"id": "AAA", "title": "Done", "duration": 120.0,
                 "webpage_url": "https://www.youtube.com/watch?v=AAA"}],
            "https://www.youtube.com/@DragonsDenGlobal/videos": [
                {"id": "BBB", "title": "Fresh", "duration": 120.0,
                 "webpage_url": "https://www.youtube.com/watch?v=BBB"}],
        }
        with tempfile.TemporaryDirectory() as tmp:
            payload, _ = self._run_finder(tmp, entries, ["AAA#1", "AAA#2", "AAA#3"])
            self.assertTrue(payload["candidates"], "rotation must hop to the second feed")
            self.assertEqual(payload["candidates"][0]["id"], "BBB#1")
            self.assertEqual(payload["channel"],
                             "https://www.youtube.com/@DragonsDenGlobal/videos")

    def test_main_starts_at_the_rotation_cursor(self):
        import tempfile
        entries = {
            "https://www.youtube.com/@SharkTankGlobal/videos": [
                {"id": "AAA", "title": "Shark", "duration": 120.0,
                 "webpage_url": "https://www.youtube.com/watch?v=AAA"}],
            "https://www.youtube.com/@DragonsDenGlobal/videos": [
                {"id": "BBB", "title": "Den", "duration": 120.0,
                 "webpage_url": "https://www.youtube.com/watch?v=BBB"}],
        }
        with tempfile.TemporaryDirectory() as tmp:
            payload, rotation = self._run_finder(tmp, entries, [], rotation_offset=1)
            self.assertEqual(payload["candidates"][0]["id"], "BBB#1",
                             "cursor=1 must start at the second feed")
            self.assertEqual(json.loads(Path(rotation).read_text(encoding="utf-8"))["offset"], 2)


if __name__ == "__main__":
    unittest.main()
