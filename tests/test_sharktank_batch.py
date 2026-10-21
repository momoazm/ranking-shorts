"""Guards for the Shark Tank batch poster, the kinetic format and the host ladder.

Why these exist (2026-10-21 audit):
  * the orchestrator built exactly ONE part per run, so an 8-part episode took 8 slots;
  * the ledgers lived only in the Actions cache, whose post-step is success-gated, so a run
    that posted a part and then failed re-posted the same part next run (Part 2/8, 5 runs);
  * the failing posts were the ones hosted on tmpfiles.org, which served an HTML error page
    to Instagram's transcoder (progressive_video_not_ready / MediaInfoExtractionException);
  * the post titles/overlay were raw transcript fragments with a "(Part N/N)" stamp.

Everything here is offline: the network edges are stubs.
"""

import argparse
import json
import os
import shutil
import sys
import tempfile
import time
import types
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))

import build_clip  # noqa: E402
import host_public  # noqa: E402
import rank_autopost  # noqa: E402
import title_part  # noqa: E402


def part(vid, index, total, start=None):
    """One finder candidate, with exactly the fields the batch reads."""
    return {
        "id": f"{vid}#{index}", "video_id": vid, "part_index": index, "part_total": total,
        "title": f"A Crazy Pitch (Part {index}/{total})",
        "source_title": "A Crazy Pitch | Shark Tank US | Shark Tank Global",
        "part_label": f"(Part {index}/{total})",
        "start": round((index - 1) * 58.7, 2) if start is None else start,
        "end": round(index * 58.7, 2), "duration": 58.7,
        "url": f"https://www.youtube.com/watch?v={vid}",
        "channel": "Shark Tank Global", "uploader": "Shark Tank Global",
        "source": "youtube", "source_feed": "https://www.youtube.com/@SharkTankGlobal/videos",
        "content_type": "sharktank_part", "content_policy": "sharktank-only", "rank": None,
    }


class BatchPlannerTest(unittest.TestCase):
    """The batch posts N parts per run and never lets one part block the rest."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.final_part = os.path.join(self.tmp, "part.mp4")
        Path(self.final_part).write_bytes(b"mp4")

        patches = [
            ("SHARKTANK_ATTEMPTS", os.path.join(self.tmp, "attempts.json")),
            ("SHARKTANK_DAILY", os.path.join(self.tmp, "daily.json")),
            ("HISTORY", os.path.join(self.tmp, "used.json")),
            ("SHARKTANK_BATCH_RESULT", os.path.join(self.tmp, "batch.json")),
            ("SHARKTANK_SCRATCH", os.path.join(self.tmp, "scratch")),
            ("FINAL", os.path.join(self.tmp, "final.mp4")),
        ]
        for name, value in patches:
            patcher = mock.patch.object(rank_autopost, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        for patcher in (
                mock.patch.object(rank_autopost, "_drought_reset", lambda: None),
                mock.patch.object(rank_autopost.time, "sleep", lambda *_a, **_k: None)):
            patcher.start()
            self.addCleanup(patcher.stop)

        self.built = []
        self.fetches = []
        self.publish_patcher = mock.patch.object(
            rank_autopost, "_publish_one_part", side_effect=self._fake_publish)
        self.publish_patcher.start()
        self.addCleanup(self.publish_patcher.stop)
        self.tool_patcher = mock.patch.object(
            rank_autopost, "run_tool_safe", side_effect=self._fake_tool)
        self.tool_patcher.start()
        self.addCleanup(self.tool_patcher.stop)

    def _fake_tool(self, name, args, timeout=None):
        if name == "fetch_source.py":
            self.fetches.append(args[args.index("--url") + 1])
            return {"path": os.path.join(self.tmp, "source.mp4")}, None
        raise AssertionError(f"unexpected tool in the batch planner: {name}")

    def _fake_publish(self, entry, src, args, platforms, required_platforms, build_timeout=600):
        self.built.append(entry["id"])
        return {"id": entry["id"], "video_id": entry["video_id"],
                "part_index": entry["part_index"], "status": "published",
                "title": f"Title {entry['id']}", "video": self.final_part,
                "delivery": {"instagram": {"media_id": "m-" + entry["id"]}},
                "required_delivery_failures": []}

    def _args(self, parts=4, gap=45.0, deadline=600.0):
        return argparse.Namespace(parts_per_run=parts, part_gap_sec=gap,
                                  batch_deadline_sec=deadline, privacy="public",
                                  tiktok_privacy=None, keep_tmp=True)

    def _run(self, pool, **kwargs):
        return rank_autopost.run_sharktank_batch(
            pool, self._args(**kwargs), ["instagram"], {"instagram"}, {"video": {"id": "V"}})

    def test_posts_a_batch_and_records_every_part_immediately(self):
        pool = [part("V", 1, 3), part("V", 2, 3), part("V", 3, 3)]
        batch = self._run(pool, parts=2)
        self.assertEqual(batch["status"], "uploaded")
        self.assertEqual(batch["planned"], 2)
        self.assertEqual(self.built, ["V#1", "V#2"], "one run must post more than one part")
        used = json.loads(Path(rank_autopost.HISTORY).read_text(encoding="utf-8"))["used"]
        self.assertEqual(used, ["V#1", "V#2"])
        daily = json.loads(Path(rank_autopost.SHARKTANK_DAILY).read_text(encoding="utf-8"))
        self.assertEqual(len(daily["posts"]), 2, "the 24h post budget must see both parts")
        self.assertEqual(self.fetches, ["https://www.youtube.com/watch?v=V"],
                         "one source download must serve every part")

    def test_zero_means_every_remaining_part(self):
        pool = [part("V", i, 3) for i in (1, 2, 3)]
        batch = self._run(pool, parts=0)
        self.assertEqual(batch["planned"], 3)
        self.assertEqual(batch["published"], 3)

    def test_dead_part_is_skipped_without_blocking_the_rest(self):
        Path(rank_autopost.SHARKTANK_ATTEMPTS).write_text(json.dumps({"parts": {
            "V#1": {"count": 3, "last_at": time.time()}}}), encoding="utf-8")
        pool = [part("V", 1, 3), part("V", 2, 3), part("V", 3, 3)]
        batch = self._run(pool, parts=4)
        self.assertEqual(self.built, ["V#2", "V#3"])
        self.assertEqual([s["id"] for s in batch["skipped_strikes"]], ["V#1"])
        self.assertEqual(batch["planned"], 2, "a struck part must not consume a batch slot")
        self.assertEqual(batch["published"], 2)

    def _used(self):
        path = Path(rank_autopost.HISTORY)
        if not path.is_file():
            return []
        return json.loads(path.read_text(encoding="utf-8"))["used"]

    def test_a_failed_part_is_struck_but_never_deleted(self):
        def failing(entry, *a, **k):
            self.built.append(entry["id"])
            return {"id": entry["id"], "status": "build_failed", "error": "renderer"}

        with mock.patch.object(rank_autopost, "_publish_one_part", side_effect=failing):
            batch = self._run([part("V", 1, 2), part("V", 2, 2)], parts=0)
        self.assertEqual(batch["status"], "delivery_failed")
        self.assertEqual(batch["failed"], 2)
        attempts = json.loads(Path(rank_autopost.SHARKTANK_ATTEMPTS).read_text(encoding="utf-8"))
        self.assertEqual(attempts["parts"]["V#1"]["count"], 1, "a failure is a per-PART strike")
        self.assertEqual(attempts["parts"]["V#2"]["count"], 1)
        self.assertEqual(self._used(), [], "nothing posted means nothing is consumed")

    def test_rolling_daily_budget_stops_the_batch(self):
        Path(rank_autopost.SHARKTANK_DAILY).write_text(json.dumps(
            {"posts": [time.time()] * 15}), encoding="utf-8")
        batch = self._run([part("V", 1, 2), part("V", 2, 2)], parts=0)
        self.assertEqual(batch["status"], "daily_budget_exhausted")
        self.assertEqual(batch["planned"], 0)
        self.assertEqual(self.built, [])

    def test_deadline_skips_the_remaining_parts(self):
        batch = self._run([part("V", 1, 2), part("V", 2, 2)], parts=0, deadline=60.0)
        self.assertEqual(self.built, [], "no render can fit in the remaining budget")
        self.assertEqual([r["status"] for r in batch["results"]],
                         ["skipped_deadline", "skipped_deadline"])
        self.assertEqual(batch["status"], "no_parts_posted")

    def test_downloads_once_per_video_and_can_cross_into_the_next_episode(self):
        pool = [part("A", 1, 1), part("B", 1, 2), part("B", 2, 2)]
        batch = self._run(pool, parts=0)
        self.assertEqual(self.built, ["A#1", "B#1", "B#2"])
        self.assertEqual(self.fetches, ["https://www.youtube.com/watch?v=A",
                                        "https://www.youtube.com/watch?v=B"])
        self.assertEqual(batch["published"], 3)

    def test_bot_walled_source_skips_its_parts_and_continues(self):
        def tool(name, args, timeout=None):
            if name == "fetch_source.py":
                url = args[args.index("--url") + 1]
                self.fetches.append(url)
                if "VIDAAA" in url:
                    return None, "fetch_source.py failed: download failed: HTTP 403"
                return {"path": os.path.join(self.tmp, "source.mp4")}, None
            raise AssertionError(name)

        with mock.patch.object(rank_autopost, "run_tool_safe", side_effect=tool), \
                mock.patch.object(rank_autopost, "_record_video_download_failure") as strike:
            batch = self._run([part("VIDAAA", 1, 2), part("VIDAAA", 2, 2),
                               part("VIDBBB", 1, 1)], parts=0)
        self.assertEqual(self.built, ["VIDBBB#1"], "a walled episode must not burn the slot")
        self.assertEqual([r["status"] for r in batch["results"][:2]],
                         ["source_failed", "source_failed"])
        self.assertEqual(strike.call_count, 1, "the walled video is demoted once, not per part")


class KineticOverlayTest(unittest.TestCase):
    """The competitor format: persistent multi-color banner + word caps, no title card."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)

    def _render(self, words=None, cta="Follow for more deals"):
        out = os.path.join(self.tmp, "overlay.ass")
        build_clip.build_kinetic_ass(
            "I came in asking for $150,000 for 10% of my company",
            "@itsmomoclips", 12.0, out, words=words, cta_dur=2.2, cta_text=cta, theme={})
        return Path(out).read_text(encoding="utf-8")

    @staticmethod
    def _events(text, style):
        return [line for line in text.splitlines()
                if line.startswith("Dialogue:") and f",{style}," in line]

    def test_no_title_card_or_badge_and_a_persistent_banner(self):
        text = self._render()
        self.assertIn("Style: HookBanner", text)
        self.assertNotIn("Style: Title,", text, "the old top title card must be gone")
        self.assertNotIn("Style: Badge,", text)
        banner = self._events(text, "HookBanner")
        self.assertEqual(len(banner), 1)
        self.assertTrue(banner[0].startswith("Dialogue: 0,0:00:00.00,0:00:12.00"),
                        "the hook banner must stay up for the whole clip")
        self.assertNotIn("(Part", text, "a part label must never be burned in")

    def test_banner_is_at_most_three_lines_and_multi_color(self):
        text = self._render()
        banner = self._events(text, "HookBanner")[0]
        payload = banner.split(",", 9)[-1]
        self.assertLessEqual(len(payload.split("\\N")), 3)
        self.assertIn("150,000", payload)
        gold = build_clip.hex_to_ass_bgr("#E6B23A")
        self.assertIn("{\\c" + gold + "}", payload, "the money must be gold-tagged")

    def test_word_captions_highlight_each_active_word(self):
        words = [{"w": "i", "start": 0.0, "end": 0.2},
                 {"w": "want", "start": 0.25, "end": 0.5},
                 {"w": "150,000", "start": 0.55, "end": 1.0},
                 {"w": "dollars", "start": 1.05, "end": 1.4}]
        text = self._render(words=words)
        caps = self._events(text, "WordCap")
        self.assertEqual(len(caps), len(words), "every word gets its own highlight event")
        self.assertIn("{\\c" + build_clip.hex_to_ass_bgr("#E6B23A") + "\\fscx110", caps[0])

    def test_handle_and_cta_are_on_screen(self):
        text = self._render()
        handle = self._events(text, "Handle")
        self.assertEqual(len(handle), 1)
        self.assertIn("@itsmomoclips", handle[0])
        cta = self._events(text, "CTA")
        self.assertEqual(len(cta), 1)
        self.assertIn("FOLLOW FOR MORE DEALS", cta[0])
        self.assertIn(build_clip._ass_time(9.8), cta[0], "the CTA owns the last 2.2s")


class TitleFallbackTest(unittest.TestCase):
    """A deterministic title must read as a sentence, never as an ASR fragment."""

    TRANSCRIPT = ("and so I walked in and told them I want one hundred and fifty thousand "
                  "dollars for ten percent of my company and they all looked at me like I "
                  "was crazy").split()

    def setUp(self):
        self.transcript = {"words": [{"w": word} for word in self.TRANSCRIPT]}

    def test_title_is_a_complete_sentence_with_no_part_label(self):
        title = title_part.deterministic_title(
            self.transcript,
            "Entrepreneur Pitches a Crazy Idea (Part 3/8) | Shark Tank US | Shark Tank Global")
        self.assertIsNone(title_part.title_problem(title), title)
        self.assertNotRegex(title, r"\(Part \d+/\d+\)")
        self.assertTrue(title.endswith((".", "!", "?")), title)
        self.assertTrue(title[0].isupper() or title[0].isdigit(), title)

    def test_money_is_normalised_and_never_cut_mid_word(self):
        title = title_part.deterministic_title(self.transcript, "A Crazy Pitch")
        self.assertIn("$150,000", title)
        # Every alphabetic token in the title must be a WHOLE word somebody actually said:
        # this is the check that fails on `[:76]` ASR fragments ("...they were startin").
        import re
        spoken = set(re.findall(r"[a-z]+", " ".join(self.TRANSCRIPT).lower()))
        for word in re.findall(r"[a-z]+", title.lower()):
            self.assertIn(word, spoken, f"'{word}' is not a complete spoken word")

    def test_word_cut_never_splits_a_word(self):
        cut = title_part.word_cut("A very long sentence about a business deal that keeps "
                                  "going and going without any pause", 40)
        self.assertLessEqual(len(cut), 41)
        self.assertTrue(cut.endswith("."), cut)
        self.assertNotIn("busines.", cut)

    def test_hook_is_short_and_uppercase(self):
        hook = title_part.deterministic_hook("He Turned Down $150,000 and Walked Away.")
        self.assertTrue(hook)
        self.assertEqual(hook, hook.upper())
        self.assertLessEqual(len(hook), 28)


class TitleLLMTest(unittest.TestCase):
    """The Groq path failed on EVERY part with `json_validate_failed ... failed_generation: ''`
    because gpt-oss-120b is a reasoning model and `max_tokens=300` was consumed by the hidden
    reasoning before any JSON was emitted. A title silently degraded to the deterministic
    sentence, and a Groq rate limit took the whole path down with it."""

    GOOD = '{"title": "Couple seeks $55,000 for 25% of their underwear business.", ' \
           '"hook": "$55K FOR 25%"}'

    def _client(self, *, content=GOOD, raises=None):
        create = mock.Mock()
        if raises:
            create.side_effect = raises
        else:
            message = types.SimpleNamespace(content=content)
            create.return_value = types.SimpleNamespace(
                choices=[types.SimpleNamespace(message=message)])
        groq = types.SimpleNamespace(Groq=mock.Mock(return_value=types.SimpleNamespace(
            chat=types.SimpleNamespace(completions=types.SimpleNamespace(create=create)))))
        return groq, create

    def test_reasoning_model_gets_a_completion_budget_not_a_prompt_budget(self):
        groq, create = self._client()
        chain = mock.Mock(side_effect=RuntimeError("chain should not be needed"))
        with mock.patch.dict(sys.modules, {"groq": groq, "_llm": types.SimpleNamespace(
                llm_complete=chain, parse_json=json.loads)}), \
             mock.patch.dict(os.environ, {"GROQ_API_KEY": "test-key", "TITLE_MODEL": ""}):
            data, provider = title_part._llm_title("we came in asking for $55,000", "", "")
        self.assertEqual(provider, "groq")
        self.assertIn("$55,000", data["title"])
        chain.assert_not_called()
        kwargs = create.call_args.kwargs
        self.assertNotIn("max_tokens", kwargs, "max_tokens starves the reasoning tokens")
        self.assertGreaterEqual(kwargs["max_completion_tokens"], 1000)
        self.assertEqual(kwargs["reasoning_effort"], "low")

    def test_a_groq_outage_falls_back_to_the_shared_chain(self):
        groq, _ = self._client(raises=RuntimeError("429 rate limit"))
        chain = mock.Mock(return_value={"text": self.GOOD, "provider": "openrouter-nemotron"})
        with mock.patch.dict(sys.modules, {"groq": groq,
                                           "_llm": types.SimpleNamespace(
                                               llm_complete=chain,
                                               parse_json=lambda raw: json.loads(raw))}), \
             mock.patch.dict(os.environ, {"GROQ_API_KEY": "test-key"}):
            data, provider = title_part._llm_title("we came in asking for $55,000", "", "")
        self.assertEqual(provider, "openrouter-nemotron")
        self.assertTrue(data["hook"])
        chain.assert_called_once()
        self.assertTrue(chain.call_args.kwargs["json_mode"])

    def test_both_paths_down_keeps_the_deterministic_title(self):
        groq, _ = self._client(raises=RuntimeError("429"))
        chain = mock.Mock(side_effect=RuntimeError("chain down"))
        transcript = {"words": [{"w": w} for w in
                                "they offered me fifty thousand dollars for ten percent".split()]}
        with mock.patch.dict(sys.modules, {"groq": groq,
                                           "_llm": types.SimpleNamespace(
                                               llm_complete=chain, parse_json=json.loads)}), \
             mock.patch.dict(os.environ, {"GROQ_API_KEY": "test-key"}):
            result = title_part.generate(transcript, "", "Shark Tank")
        self.assertEqual(result["provider"], "deterministic")
        self.assertIn("llm_error", result)
        self.assertIsNone(title_part.title_problem(result["title"]), result["title"])

    def test_exotic_hyphens_and_no_break_spaces_are_normalised(self):
        # gpt-oss emitted a U+2011 hyphen; it renders as tofu in the burned ASS banner.
        self.assertEqual(title_part.clean_sentence("A flatulence\u2011proof pitch."),
                         "A flatulence-proof pitch.")
        self.assertEqual(title_part._valid_hook("$55,000\u00a0FOR\u00a025%"),
                         "$55,000 FOR 25%")


class HookLayoutTest(unittest.TestCase):
    """A long banner must shrink the type, never truncate the sentence with an ellipsis.

    The 2026-10-21 no-upload run (39554901356) burned
    "DRAGONS CAN'T / FIGURE OUT WHAT / THIS ENTREPRENEUR'S ..." -- the hook's payoff was
    cut off by the fixed 3-line/19-char banner."""

    def test_a_long_hook_is_never_truncated(self):
        hook = "Dragons Can't Figure Out What This Entrepreneur's Selling"
        size, lines = build_clip._hook_layout(hook)
        self.assertEqual([token for line in lines for token in line], hook.split())
        self.assertLessEqual(len(lines), 3)
        self.assertLess(size, 100)

    def test_a_short_hook_keeps_the_big_type(self):
        size, lines = build_clip._hook_layout("$55,000 FOR 25%")
        self.assertEqual(size, 100)
        self.assertEqual(lines, [["$55,000", "FOR", "25%"]])

    def test_banner_colors_the_money_and_keeps_every_word(self):
        colors = {"gold": build_clip.hex_to_ass_bgr("#E6B23A"),
                  "gold_light": build_clip.hex_to_ass_bgr("#F4D277"),
                  "teal": build_clip.hex_to_ass_bgr("#2E7C8C"),
                  "red": build_clip.hex_to_ass_bgr("#E2564A"),
                  "white": build_clip.hex_to_ass_bgr("#FFFFFF")}
        size, lines = build_clip._hook_layout("HE LOST $100,000")
        text = build_clip._kinetic_banner("HE LOST $100,000", colors, lines)
        self.assertIn("\\c" + colors["red"] + "}LOST", text)
        self.assertIn("\\c" + colors["gold"] + "}$100,000", text)
        self.assertEqual(text.replace("\\N", " ").count(" "), 2)


class HostLadderTest(unittest.TestCase):
    """Never hand Instagram a URL that serves an HTML error page (the tmpfiles failure)."""


    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.tmp, ignore_errors=True)
        self.video = os.path.join(self.tmp, "clip.mp4")
        Path(self.video).write_bytes(b"\x00" * 64)

    def _providers(self, order):
        return [(name, mock.Mock(side_effect=(lambda p, url=url: url), __name__=name))
                for name, url in order]

    def test_falls_through_to_the_next_host_and_reports_the_provider(self):
        providers = self._providers([("broken", "https://broken/x.mp4"),
                                     ("good", "https://good/x.mp4")])
        providers[0][1].side_effect = RuntimeError("upload refused")

        def verify(url, expected_size=0):
            if "broken" in url:
                raise RuntimeError("not video bytes")

        with mock.patch.object(host_public, "PROVIDERS", providers), \
                mock.patch.object(host_public, "verify_public_url", side_effect=verify):
            url, provider = host_public.host(self.video)
        self.assertEqual((url, provider), ("https://good/x.mp4", "good"))

    def test_exclude_forces_the_retry_onto_a_different_host(self):
        providers = self._providers([("catbox", "https://catbox/x.mp4"),
                                     ("litterbox", "https://litterbox/x.mp4")])
        with mock.patch.object(host_public, "PROVIDERS", providers), \
                mock.patch.object(host_public, "verify_public_url"):
            url, provider = host_public.host(self.video, exclude=["catbox"])
        self.assertEqual((url, provider), ("https://litterbox/x.mp4", "litterbox"))
        providers[0][1].assert_not_called()

    def test_verified_host_must_serve_video_bytes(self):
        class _Response:
            status_code = 200
            headers = {"content-type": "text/html; charset=utf-8", "content-length": "60"}

            def iter_bytes(self):
                yield b"<!DOCTYPE html><html>error</html>" * 2

        class _Stream:
            def __enter__(self):
                return _Response()

            def __exit__(self, *exc):
                return False

        fake_httpx = types.ModuleType("httpx")
        fake_httpx.stream = lambda *a, **k: _Stream()
        with mock.patch.dict(sys.modules, {"httpx": fake_httpx}):
            with self.assertRaises(RuntimeError):
                host_public.verify_public_url("https://tmpfiles.org/dl/x.mp4")


if __name__ == "__main__":
    unittest.main()
