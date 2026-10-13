"""Guards for the Shark Tank "finish the chop you started" contract.

The finder used to always offer the NEWEST upload of whichever feed the round-robin landed
on. Because the orchestrator posts exactly ONE part per run, every new episode displaced an
unfinished video and parts 3..N were never offered again -- measured over 2026-10-03..05,
only 7 of 59 parts ever reached the channel.

These tests pin the three properties that close that gap, and drive the REAL main() (only
the network edges are stubbed) so a refactor cannot keep the helpers while losing the
behaviour.
"""

import json
import os
import shutil
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))

import find_sharktank_parts  # noqa: E402
import _common  # noqa: E402



# A 300s upload splits into ceil(300 / 59.5) = 6 near-50s parts: split_parts clamps the
# ceiling to MAX_SOURCE_SECS, so fixtures must use the real count rather than 5.
PARTS_300 = len(find_sharktank_parts.split_parts(300.0))


def entry(vid, duration=300.0, channel="Shark Tank Global"):
    """Flat feed entry as yt-dlp returns it (id/title/duration/webpage_url)."""
    return {"id": vid, "title": f"{vid} pitch", "duration": duration,
            "channel": channel, "uploader": channel,
            "webpage_url": f"https://www.youtube.com/watch?v={vid}"}


def pick(vid, parts_total, remaining, feed="feedA", duration=300.0):
    parts = [(0.0, 60.0)] * parts_total
    return (feed, {"id": vid, "title": vid}, parts, list(remaining), duration)


class OrderPicksTest(unittest.TestCase):
    def test_part_posted_video_beats_the_newest_upload(self):
        """The core fix: an unfinished chop keeps the front slot over a brand-new upload."""
        newest = pick("NEW", 5, [1, 2, 3, 4, 5])     # untouched -> brand new
        older = pick("OLD", 5, [3, 4, 5])            # parts 1-2 already posted
        ordered = find_sharktank_parts.order_picks([newest, older])
        self.assertEqual(ordered[0][1]["id"], "OLD",
                         "a partially-posted video must never lose to a newer upload")

    def test_closest_to_done_finishes_first(self):
        """Among in-progress uploads, the one nearest completion wins (fewest parts left)."""
        big = pick("BIG", 20, list(range(10, 21)))
        nearly = pick("NEAR", 8, [7, 8])
        ordered = find_sharktank_parts.order_picks([big, nearly])
        self.assertEqual([p[1]["id"] for p in ordered], ["NEAR", "BIG"])

    def test_new_uploads_keep_the_callers_rotated_order(self):
        """Ties are stable, so feed round-robin still decides which NEW upload opens first."""
        first = pick("A", 5, [1, 2, 3, 4, 5], feed="feedA")
        second = pick("B", 5, [1, 2, 3, 4, 5], feed="feedB")
        third = pick("C", 5, [1, 2, 3, 4, 5], feed="feedC")
        ordered = find_sharktank_parts.order_picks([first, second, third])
        self.assertEqual([p[1]["id"] for p in ordered], ["A", "B", "C"])

    def test_in_progress_still_outranks_every_new_upload(self):
        partial = pick("OLD", 5, [5])
        news = [pick(f"N{i}", 5, [1, 2, 3, 4, 5]) for i in range(6)]
        ordered = find_sharktank_parts.order_picks(news + [partial])
        self.assertEqual(ordered[0][1]["id"], "OLD",
                         "the in-progress chop leads, however many new uploads are waiting")
        self.assertEqual([p[1]["id"] for p in ordered[1:]], [f"N{i}" for i in range(6)],
                         "new uploads keep their rotated order behind it")

    def test_failing_video_is_demoted_only_after_two_strikes(self):
        """A dead upload must not hog the front of the queue -- but one blip is not fatal."""
        partial = pick("OLD", 5, [3, 4, 5])
        fresh = pick("NEW", 5, [1, 2, 3, 4, 5])
        now = time.time()

        one = {"OLD": {"count": 1, "last_at": now}}
        self.assertEqual(find_sharktank_parts.order_picks([partial, fresh], one)[0][1]["id"],
                         "OLD", "a single failed download must not demote the video")

        two = {"OLD": {"count": 2, "last_at": now}}
        ordered = find_sharktank_parts.order_picks([partial, fresh], two)
        self.assertEqual(ordered[-1][1]["id"], "OLD",
                         "after two strikes the in-progress video drops behind new uploads")

    def test_failure_strikes_expire_so_a_recovered_upload_can_finish(self):
        stale = {"OLD": {"count": 3,
                         "last_at": time.time() - find_sharktank_parts.FAILURE_WINDOW_SEC - 5}}
        self.assertEqual(find_sharktank_parts.pick_priority(pick("OLD", 5, [3, 4, 5]), stale),
                         (0, 3), "expired strikes must not permanently abandon a video")

    def test_part_total_and_remaining_are_both_counted(self):
        """priority is (group, remaining) -- a 20-part video with 19 left still leads group 0."""
        self.assertEqual(find_sharktank_parts.pick_priority(pick("OLD", 20, list(range(2, 21)))), (0, 19))
        self.assertEqual(find_sharktank_parts.pick_priority(pick("NEW", 5, [1, 2, 3, 4, 5])), (1, 0))


class ProgressStoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.path = self.tmp / "state" / "inprogress.json"

    def test_slim_entry_keeps_exactly_what_build_candidate_reads(self):
        full = entry("V1")
        full["duration"] = 300.0
        full["part_total"] = 5
        full["feed"] = "feedA"
        slim = find_sharktank_parts.slim_entry(full)
        self.assertEqual(set(slim), {"id", "title", "channel", "uploader", "webpage_url"})
        self.assertNotIn("duration", slim, "state must not accumulate derived build fields")

    def test_a_slim_stored_entry_rebuilds_the_same_part(self):
        """A video that scrolled out of the feed window must still yield an identical chop."""
        source = entry("V1", channel="Dragons' Den")
        parts = find_sharktank_parts.split_parts(300.0, 60.0, 20)
        direct = find_sharktank_parts.build_candidate(source, parts, 3, parts[2][0], parts[2][1], "feedA")
        rebuilt = find_sharktank_parts.build_candidate(dict(find_sharktank_parts.slim_entry(source)),
                                                       parts, 3, parts[2][0], parts[2][1], "feedA")
        for field in ("id", "video_id", "part_index", "part_total", "title", "source_title",
                      "start", "end", "url", "channel", "uploader", "content_type",
                      "content_policy"):
            self.assertEqual(rebuilt[field], direct[field], f"field {field} diverged")

    def test_load_progress_tolerates_missing_and_corrupt_files(self):
        self.assertEqual(find_sharktank_parts.load_progress(self.path), ({}, {}))
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text("{not json", encoding="utf-8")
        self.assertEqual(find_sharktank_parts.load_progress(self.path), ({}, {}))
        self.path.write_text(json.dumps([1, 2, 3]), encoding="utf-8")
        self.assertEqual(find_sharktank_parts.load_progress(self.path), ({}, {}))

    def test_save_progress_round_trips_both_maps(self):
        videos = {"V1": {**find_sharktank_parts.slim_entry(entry("V1")), "duration": 300.0}}
        failures = {"V2": {"count": 2, "last_at": 1.0}}
        find_sharktank_parts.save_progress(self.path, videos, failures)
        self.assertEqual(find_sharktank_parts.load_progress(self.path), (videos, failures))

    def test_record_download_failure_increments_and_never_raises(self):
        find_sharktank_parts.record_download_failure("V1", path=str(self.path))
        find_sharktank_parts.record_download_failure("V1", path=str(self.path))
        _videos, failures = find_sharktank_parts.load_progress(self.path)
        self.assertEqual(failures["V1"]["count"], 2)
        self.assertGreater(failures["V1"]["last_at"], 0)

        # Recording must never be able to fail the run that hit it.
        blocker = self.tmp / "blocker"
        blocker.write_text("i am a file, not a directory", encoding="utf-8")
        find_sharktank_parts.record_download_failure("V1", path=str(blocker / "x.json"))
        find_sharktank_parts.record_download_failure("", path=str(self.path))   # no-op
        self.assertEqual(find_sharktank_parts.load_progress(blocker / "x.json"), ({}, {}))

    def test_a_fresh_window_starts_a_fresh_count(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        old = time.time() - find_sharktank_parts.FAILURE_WINDOW_SEC - 5
        self.path.write_text(json.dumps(
            {"videos": {}, "failures": {"V1": {"count": 4, "last_at": old}}}), encoding="utf-8")
        find_sharktank_parts.record_download_failure("V1", path=str(self.path))
        _videos, failures = find_sharktank_parts.load_progress(self.path)
        self.assertEqual(failures["V1"]["count"], 1, "expired strikes must reset, not accumulate")


class FinderBehaviourTest(unittest.TestCase):
    """Drive the real main() with only search/probe/emit stubbed."""

    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.history = self.tmp / "used.json"
        self.rotation = self.tmp / "rotation.json"
        self.inprogress = self.tmp / "inprogress.json"
        self.out = self.tmp / "candidates.json"
        self.emitted = []

    def write_used(self, ids):
        self.history.parent.mkdir(parents=True, exist_ok=True)
        self.history.write_text(json.dumps({"used": list(ids)}), encoding="utf-8")

    def write_progress(self, videos, failures=None):
        self.inprogress.parent.mkdir(parents=True, exist_ok=True)
        self.inprogress.write_text(json.dumps(
            {"videos": videos, "failures": failures or {}}), encoding="utf-8")

    def run_main(self, feeds, feed_entries, extra=()):
        """Returns the candidates file the real main() wrote."""
        def fake_search(feed, n):
            if feed not in feed_entries:
                raise RuntimeError(f"{feed} unreachable")
            return list(feed_entries[feed])

        argv = ["find_sharktank_parts",
                "--channel", ",".join(feeds),
                "--history", str(self.history),
                "--rotation", str(self.rotation),
                "--inprogress", str(self.inprogress),
                "--out", str(self.out),
                *extra]
        # fail() emits through _common's OWN namespace (a separate binding from the one
        # imported above), so the no_source contract is asserted on that payload too.
        with mock.patch.object(find_sharktank_parts, "load_env"), \
             mock.patch.object(find_sharktank_parts, "search", side_effect=fake_search), \
             mock.patch.object(find_sharktank_parts, "probe_duration",
                               side_effect=lambda e: e.get("duration")), \
             mock.patch.object(find_sharktank_parts, "emit",
                               side_effect=lambda payload: self.emitted.append(payload)), \
             mock.patch.object(_common, "emit",
                               side_effect=lambda payload: self.emitted.append(payload)), \
             mock.patch.object(sys, "argv", argv):
            find_sharktank_parts.main()
        return json.loads(self.out.read_text(encoding="utf-8"))

    def test_front_candidate_is_the_next_part_not_the_newest_upload(self):
        """Regression for the shipped bug: parts 3..N were never offered."""
        self.write_used(["OLD#1", "OLD#2"])
        result = self.run_main(
            ["feedA"],
            {"feedA": [entry("NEW"), entry("OLD")]})
        self.assertEqual(result["candidates"][0]["id"], "OLD#3",
                         "the orchestrator posts candidates[0]; it must be the unfinished chop")
        self.assertEqual(result["video"]["id"], "OLD")
        self.assertEqual(result["video"]["parts_remaining"], PARTS_300 - 2)

    def test_video_scrolled_out_of_the_feed_window_is_still_resumed(self):
        """The durable queue is what makes 'all clips uploaded' independent of --scan."""
        self.write_used(["OLD#1", "OLD#2"])
        self.write_progress({"OLD": {**find_sharktank_parts.slim_entry(entry("OLD")),
                                     "duration": 300.0, "part_total": PARTS_300, "feed": "feedA"}})
        result = self.run_main(["feedA"], {"feedA": [entry("NEW")]})
        self.assertEqual(result["candidates"][0]["id"], "OLD#3",
                         "an in-progress upload must survive leaving the scan window")

    def test_a_finished_video_is_pruned_from_the_queue(self):
        self.write_used([f"DONE#{i}" for i in range(1, PARTS_300 + 1)])
        self.write_progress({"DONE": {**find_sharktank_parts.slim_entry(entry("DONE")),
                                      "duration": 300.0, "part_total": PARTS_300, "feed": "feedA"}})
        self.run_main(["feedA"], {"feedA": [entry("DONE"), entry("NEW")]})
        stored = json.loads(self.inprogress.read_text(encoding="utf-8"))
        self.assertNotIn("DONE", stored["videos"], "a fully-posted chop must leave the queue")
        self.assertIn("NEW", stored["videos"], "the chop being opened is remembered for next run")

    def test_a_down_feed_does_not_lose_its_in_progress_video(self):
        """Feed outage + scroll-out combined must not silently abandon a chop."""
        self.write_used(["OLD#1", "OLD#2"])
        self.write_progress({"OLD": {**find_sharktank_parts.slim_entry(entry("OLD")),
                                     "duration": 300.0, "part_total": PARTS_300, "feed": "feedDown"}})
        result = self.run_main(["feedDown", "feedA"], {"feedA": [entry("NEW")]})
        self.assertEqual(result["candidates"][0]["id"], "OLD#3")
        stored = json.loads(self.inprogress.read_text(encoding="utf-8"))
        self.assertIn("OLD", stored["videos"])

    def test_video_that_keeps_failing_stops_owning_the_front_slot(self):
        """Non-vacuity for the demotion guard: a 2-strike chop must not block the channel."""
        self.write_used(["OLD#1", "OLD#2"])
        self.write_progress({"OLD": {**find_sharktank_parts.slim_entry(entry("OLD")),
                                     "duration": 300.0, "part_total": PARTS_300, "feed": "feedA"}},
                            failures={"OLD": {"count": 2, "last_at": time.time()}})
        result = self.run_main(["feedA"], {"feedA": [entry("NEW"), entry("OLD")]})
        self.assertEqual(result["candidates"][0]["id"], "NEW#1")

    def test_a_strike_demotes_but_never_removes_a_video(self):
        """Even at 3 strikes a chop stays eligible -- it must still win when it is the only
        option, otherwise a dead-looking upload's parts are lost forever."""
        self.write_used(["OLD#1", "OLD#2"])
        self.write_progress({"OLD": {**find_sharktank_parts.slim_entry(entry("OLD")),
                                     "duration": 300.0, "part_total": PARTS_300, "feed": "feedA"}},
                            failures={"OLD": {"count": 3, "last_at": time.time()}})
        result = self.run_main(["feedA"], {"feedA": [entry("OLD")]})
        self.assertEqual(result["candidates"][0]["id"], "OLD#3",
                         "a demoted chop must remain the answer when nothing else is left")

    def test_a_chop_we_cannot_re_evaluate_is_carried_not_dropped(self):
        """A lowered --max-parts must not silently delete a partly-posted chop from the queue."""
        self.write_used(["OLD#1", "OLD#2"])
        self.write_progress({"OLD": {**find_sharktank_parts.slim_entry(entry("OLD")),
                                     "duration": 300.0, "part_total": PARTS_300, "feed": "feedA"}})
        # 300s needs 6 parts, so --max-parts 3 makes OLD ineligible; NEW at 120s still fits.
        result = self.run_main(["feedA"], {"feedA": [entry("OLD"), entry("NEW", duration=120.0)]},
                               extra=["--max-parts", "3"])
        self.assertEqual(result["candidates"][0]["id"], "NEW#1")
        stored = json.loads(self.inprogress.read_text(encoding="utf-8"))
        self.assertIn("OLD", stored["videos"],
                      "an upload that cannot be re-evaluated must be carried, never dropped")

    def test_queue_write_is_replace_based_not_truncate(self):
        """A truncate-write killed mid-dump reads back as empty, and load_progress treats an
        empty/corrupt file as an empty queue -- so the next save would wipe every chop.

        Pinned two ways, because merely checking that no `.tmp` remains would also pass for
        a plain `open(path, "w")` truncate-write: (a) the commit must go through os.replace,
        and (b) a stale corrupt temp file left by an earlier crash must be cleared, which a
        truncate-write never touches at all.
        """
        self.inprogress.write_text("{corrupt partial dump", encoding="utf-8")
        stale = self.tmp / "inprogress.json.tmp"
        stale.write_text("{killed mid-dump", encoding="utf-8")
        self.write_used(["NEW#1"])

        replaced = []
        real_replace = os.replace
        with mock.patch.object(find_sharktank_parts.os, "replace",
                               side_effect=lambda src, dst: (replaced.append((src, dst)),
                                                             real_replace(src, dst))):
            self.run_main(["feedA"], {"feedA": [entry("NEW")]})

        self.assertEqual([(Path(src).name, Path(dst).name) for src, dst in replaced],
                         [("inprogress.json.tmp", "inprogress.json")],
                         "the queue must be committed with os.replace, not a direct write")
        self.assertFalse(stale.exists(), "the temp file must be renamed away")
        stored = json.loads(self.inprogress.read_text(encoding="utf-8"))
        self.assertIn("NEW", stored["videos"], "a corrupt queue must recover, not stay empty")

    def test_every_video_in_the_emitted_pool_is_remembered(self):
        """The orchestrator may post from a FALLBACK video behind the front pick, so every
        candidate's upload must be queued, not only picks[0]. Otherwise a fallback post that
        then scrolls out of the scan window loses parts 2..N for good -- the original bug
        re-entering through the failure path.
        """
        self.write_used(["FRONT#1"])
        result = self.run_main(
            ["feedA", "feedB"],
            {"feedA": [entry("FRONT"), entry("MID")], "feedB": [entry("FALLBACK")]})
        queued = {c["video_id"] for c in result["candidates"]}
        self.assertEqual(queued, {"FRONT", "MID", "FALLBACK"})
        stored = json.loads(self.inprogress.read_text(encoding="utf-8"))
        self.assertTrue(queued <= set(stored["videos"]),
                        f"candidates not remembered: {sorted(queued - set(stored['videos']))}")

    def test_a_fallback_post_survives_scroll_out_across_two_runs(self):
        """The full failure sequence, replayed over two real runs.

        Run 1 emits a front pick and a fallback; the orchestrator's front download fails, so
        it posts part 1 of the FALLBACK instead. Run 2 must still offer FALLBACK's part 2
        even though the upload has scrolled out of the scan window entirely -- otherwise the
        fallback's parts 2..N are lost, which is the original bug re-entering.
        """
        self.run_main(["feedA"], {"feedA": [entry("FRONT"), entry("FALLBACK")]})
        stored = json.loads(self.inprogress.read_text(encoding="utf-8"))
        self.assertEqual(set(stored["videos"]), {"FRONT", "FALLBACK"},
                         "both the front pick and the fallback must be queued after run 1")

        # Run 2: only the fallback's part 1 was posted, and both older uploads have since
        # scrolled out of the feed's scan window.
        self.write_used(["FALLBACK#1"])
        result = self.run_main(["feedA"], {"feedA": [entry("NEWEP")]})
        self.assertEqual(result["candidates"][0]["id"], "FALLBACK#2",
                         "the chop that was actually posted must resume ahead of new content")
        stored = json.loads(self.inprogress.read_text(encoding="utf-8"))
        self.assertIn("FALLBACK", stored["videos"])

    def test_a_lost_ledger_must_not_drop_a_chop_that_was_posted(self):
        """Regression guard for a data-loss path found in adversarial review.

        state/ (the posted-part ledger AND this queue) exists only in the GitHub Actions
        cache, whose post step is success()-gated. A run that posts a part and then goes red
        (an Instagram-required failure after the YouTube post, a timeout, a cancelled
        no_upload dispatch) rolls BOTH files back, so the next run sees a chop that really
        does have a live posted part with no ledger entry for it. Inferring "never started"
        from that ledger and pruning on it would delete a live chop permanently, in a green
        run -- the exact loss this queue exists to prevent.
        """
        # Run 1: the upload is queued from the pool, but its post never reaches the ledger
        # (the run went red after posting).
        self.run_main(["feedA"], {"feedA": [entry("SCROLLED")]})

        # Run 2: the ledger is empty again AND the upload has scrolled out of the feed, so
        # only the durable queue knows it still has unposted parts.
        result = self.run_main(["feedA"], {"feedA": [entry("NEWEP")]})
        stored = json.loads(self.inprogress.read_text(encoding="utf-8"))["videos"]
        self.assertIn(
            "SCROLLED", stored,
            "a chop with no ledger entry must never be pruned: the ledger can lag reality")
        offered = {c["video_id"] for c in result["candidates"]}
        self.assertIn("SCROLLED", offered,
                      "its remaining parts must still be offered for posting")

    def test_started_chops_outside_the_pool_are_all_retained(self):
        """More started chops than --max-videos: the ones behind the pool must survive too,
        or a backlog chop would vanish simply because this run did not reach it."""
        self.write_used([f"{vid}#1" for vid in ("A", "B", "C")])
        self.run_main(["feedA"], {"feedA": [entry("A"), entry("B"), entry("C")]},
                      extra=["--max-videos", "2"])
        stored = json.loads(self.inprogress.read_text(encoding="utf-8"))["videos"]
        self.assertEqual(set(stored), {"A", "B", "C"},
                         "every started chop is retained regardless of the pool size")

    def test_a_record_whose_id_does_not_match_its_key_is_skipped_not_emitted(self):
        """A corrupt record must not emit candidates carrying a None or foreign video_id,
        which would collide in the shared "<video_id>#<part>" ledger."""
        bad = {**find_sharktank_parts.slim_entry(entry("REAL")), "duration": 120.0,
               "part_total": 3, "feed": "feedA"}
        bad.pop("id")                      # the id no longer matches its queue key
        self.write_progress({"GHOST": bad})
        result = self.run_main(["feedA"], {"feedA": [entry("NEW")]})

        ids = [c["id"] for c in result["candidates"]]
        self.assertTrue(all(not i.startswith("None#") for i in ids), ids)
        self.assertNotIn("GHOST", {c["video_id"] for c in result["candidates"]})
        stored = json.loads(self.inprogress.read_text(encoding="utf-8"))["videos"]
        self.assertIn("GHOST", stored,
                      "an unreadable record is left in place, never destroyed")

    def test_the_default_queue_path_is_root_anchored_not_cwd_relative(self):
        """Without an explicit --inprogress, the queue must resolve under REPO_ROOT.

        If it resolved against the working directory, running the finder from anywhere but
        the repo root would shard the queue away from the download-failure strikes (which are
        separately ROOT-anchored), so each would never see the other's state.
        """
        captured = {}
        (self.tmp / "used.json").write_text(json.dumps({"used": []}), encoding="utf-8")
        with mock.patch.object(find_sharktank_parts, "load_env"), \
             mock.patch.object(find_sharktank_parts, "search",
                               side_effect=lambda feed, n: [entry("NEW")]), \
             mock.patch.object(find_sharktank_parts, "probe_duration",
                               side_effect=lambda e: e.get("duration")), \
             mock.patch.object(find_sharktank_parts, "load_progress", return_value=({}, {})), \
             mock.patch.object(find_sharktank_parts, "save_progress",
                               side_effect=lambda p, v, f: captured.setdefault("path", p)), \
             mock.patch.object(find_sharktank_parts, "save_rotation"), \
             mock.patch.object(sys, "argv", ["find_sharktank_parts",
                                             "--channel", "feedA",
                                             "--history", str(self.tmp / "used.json"),
                                             "--rotation", str(self.tmp / "rot.json"),
                                             "--out", str(self.tmp / "out.json")]):
            find_sharktank_parts.main()

        expected = Path(find_sharktank_parts.REPO_ROOT) / find_sharktank_parts.INPROGRESS_STATE
        self.assertEqual(Path(captured["path"]).resolve(), expected.resolve())
        self.assertTrue(Path(captured["path"]).is_absolute(),
                        "an absolute default cannot be sharded by the caller's cwd")

    def test_the_finder_never_writes_the_repo_default_queue_path(self):
        """Behavioural guard: the only queue path main() may touch is --inprogress.

        Asserts the repo's real queue is byte-identical before and after, rather than
        merely absent -- running the finder from the repo root legitimately creates that
        file, and an "it must not exist" assertion would silently go vacuous the moment
        someone did.
        """
        default_path = (Path(find_sharktank_parts.REPO_ROOT)
                        / find_sharktank_parts.INPROGRESS_STATE)

        def snapshot():
            return default_path.read_bytes() if default_path.exists() else None

        before = snapshot()
        self.write_used(["NEW#1"])
        self.run_main(["feedA"], {"feedA": [entry("NEW")]})
        self.assertEqual(snapshot(), before,
                         f"main() must never create or modify {default_path}; it takes --inprogress")
        self.assertTrue(self.inprogress.exists(), "the scratch queue must be written instead")

    def test_failure_hook_default_is_root_anchored_not_cwd_relative(self):
        """A strike recorded without an explicit path must target the repo queue, never the
        current working directory -- otherwise launching the orchestrator elsewhere would
        silently drop every strike."""
        captured = {}
        with mock.patch.object(find_sharktank_parts, "load_progress", return_value=({}, {})), \
             mock.patch.object(find_sharktank_parts, "save_progress",
                               side_effect=lambda p, v, f: captured.setdefault("path", p)), \
             mock.patch.object(find_sharktank_parts, "REPO_ROOT", self.tmp):
            find_sharktank_parts.record_download_failure("VX")
        self.assertEqual(Path(captured["path"]),
                         self.tmp / find_sharktank_parts.INPROGRESS_STATE)

    def test_rotation_still_feeds_distinct_fallback_videos(self):
        """R2 slot burn: the pool must still offer a next DISTINCT video_id."""
        self.write_used(["OLD#1", "OLD#2"])
        result = self.run_main(
            ["feedA", "feedB"],
            {"feedA": [entry("OLD")], "feedB": [entry("FEEDB")]})
        ids = [c["video_id"] for c in result["candidates"]]
        self.assertIn("OLD", ids)
        self.assertIn("FEEDB", ids, "the fallback video must stay in the pool")
        self.assertEqual(result["candidates"][0]["id"], "OLD#3")

    def test_no_eligible_upload_fails_loudly(self):
        """An all-posted pool is still a clean, inspectable no_source -- not a crash."""
        self.write_used([f"OLD#{i}" for i in range(1, PARTS_300 + 1)])
        with self.assertRaises(SystemExit):
            self.run_main(["feedA"], {"feedA": [entry("OLD")]})
        # _common.fail() emits {"error": ...} and exits 1; the orchestrator keys off that
        # shape plus the policy tag to treat it as a clean no-post.
        payload = self.emitted[0]
        self.assertIn("no eligible pitch-show upload", payload.get("error", ""))
        self.assertEqual(payload.get("content_policy"), "sharktank-only")
        self.assertEqual(payload.get("channel"), ["feedA"])
        self.assertEqual(payload.get("reasons"), ["OLD: all 6 parts already posted"])


if __name__ == "__main__":
    unittest.main()
