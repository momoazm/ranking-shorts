"""Offline tests for the Invidious sourcing fallback in build_ranking_video.

Added 2026-10-15 alongside the Instagram-first change. The fallback exists because YouTube
bot-walls the METADATA request on GitHub's datacenter IPs before any format URL is minted, so
every yt-dlp player_client route fails regardless of cookies. A public Invidious instance mints
a PO-token-signed googlevideo URL from its own clean egress, and the media is gated by that PO
token rather than by the fetcher's IP, so a datacenter fetcher can pull it without a session.

Nothing here touches the network: resolution/format selection are pure functions, and the
download() integration stubs both _download_via_invidious and _download_attempt.
"""
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))

import build_ranking_video  # noqa: E402


YOUTUBE_URL = "https://www.youtube.com/watch?v=vnUFUxUGA6M"
# Deliberately NOT a media-suffixed URL: download() has a pre-existing fast path for direct
# .mp4/.webm/.mov links, and this test is about the *fallback* being skipped for non-YouTube.
NON_YOUTUBE_URL = "https://vimeo.com/123456789"


def _entry(video=(), audio=(), extra=None):
    """Build an Invidious /api/v1/videos payload from (itag, mime, height, has_url) tuples."""
    adaptive = []
    for itag, mime, height, has_url in list(video) + list(audio):
        fmt = {"itag": itag, "type": mime}
        if height is not None:
            fmt["qualityLabel"] = height
        if has_url:
            fmt["url"] = f"https://rr1---sn-example.googlevideo.com/videoplayback?itag={itag}"
        adaptive.append(fmt)
    payload = {"title": "Shark Tank Australia", "adaptiveFormats": adaptive}
    if extra:
        payload.update(extra)
    return payload


class YoutubeVideoIdTest(unittest.TestCase):
    def test_watch_url(self):
        self.assertEqual(build_ranking_video.youtube_video_id(YOUTUBE_URL), "vnUFUxUGA6M")

    def test_shorts_url(self):
        self.assertEqual(
            build_ranking_video.youtube_video_id("https://www.youtube.com/shorts/abcDEF12345"),
            "abcDEF12345")

    def test_embed_and_live_urls(self):
        self.assertEqual(
            build_ranking_video.youtube_video_id("https://www.youtube.com/embed/vnUFUxUGA6M"),
            "vnUFUxUGA6M")
        self.assertEqual(
            build_ranking_video.youtube_video_id("https://www.youtube.com/live/vnUFUxUGA6M"),
            "vnUFUxUGA6M")

    def test_non_youtube_urls_are_rejected(self):
        for url in (NON_YOUTUBE_URL, "https://vimeo.com/12345", "", None,
                    "https://www.youtube.com/@SharkTankGlobal/videos"):
            self.assertIsNone(build_ranking_video.youtube_video_id(url), url)

    def test_short_or_malformed_ids_are_rejected(self):
        self.assertIsNone(build_ranking_video.youtube_video_id("https://www.youtube.com/watch?v=short"))


class PickFormatsTest(unittest.TestCase):
    def test_prefers_h264_and_skips_av1_vpx(self):
        entry = _entry(video=[
            (399, 'video/mp4; codecs="av01.0.08M.08"', "1080p", True),   # AV1, higher
            (137, 'video/mp4; codecs="avc1.640028"', "1080p", True),     # H.264
        ], audio=[(251, 'audio/webm; codecs="opus"', None, True)])
        video, audio = build_ranking_video._pick_formats(entry, 0)
        self.assertIn("itag=137", video)      # AV1 deliberately not chosen
        self.assertIn("itag=251", audio)      # only audio available -> opus still usable

    def test_prefers_m4a_audio(self):
        entry = _entry(video=[(137, 'video/mp4; codecs="avc1"', "1080p", True)],
                       audio=[(251, 'audio/webm; codecs="opus"', None, True),
                              (140, 'audio/mp4; codecs="mp4a.40.2"', None, True)])
        _video, audio = build_ranking_video._pick_formats(entry, 0)
        self.assertIn("itag=140", audio)

    def test_height_cap_is_respected(self):
        entry = _entry(video=[(137, 'video/mp4; codecs="avc1"', "1080p", True),
                              (133, 'video/mp4; codecs="avc1"', "360p", True)])
        video, _audio = build_ranking_video._pick_formats(entry, 360)
        self.assertIn("itag=133", video)

    def test_itag_height_map_used_when_api_omits_height(self):
        entry = _entry(video=[(137, 'video/mp4; codecs="avc1"', None, True),
                              (133, 'video/mp4; codecs="avc1"', None, True)])
        video, _audio = build_ranking_video._pick_formats(entry, 360)
        # 137 is 1080p by itag map -> over the 360 cap -> only 133 (360p) survives
        self.assertIn("itag=133", video)

    def test_formats_without_a_url_are_ignored(self):
        entry = _entry(video=[(137, 'video/mp4; codecs="avc1"', "1080p", False)])
        video, _audio = build_ranking_video._pick_formats(entry, 0)
        self.assertIsNone(video)

    def test_no_video_returns_none_pair(self):
        video, audio = build_ranking_video._pick_formats({"adaptiveFormats": []}, 0)
        self.assertIsNone(video)
        self.assertIsNone(audio)

    def test_missing_adaptive_formats_key_is_safe(self):
        video, _audio = build_ranking_video._pick_formats({"title": "x"}, 0)
        self.assertIsNone(video)


class InstanceAndToggleTest(unittest.TestCase):
    def setUp(self):
        self._saved = {k: os.environ.get(k) for k in ("INVIDIOUS_INSTANCES", "INVIDIOUS_DISABLED")}

    def tearDown(self):
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_default_instances_are_https_and_ordered(self):
        instances = build_ranking_video._invidious_instances()
        self.assertTrue(instances)
        self.assertTrue(all(u.startswith("https://") for u in instances))
        self.assertTrue(all(not u.endswith("/") for u in instances))

    def test_instances_env_override_is_parsed_and_trimmed(self):
        os.environ["INVIDIOUS_INSTANCES"] = "https://a.example/ , https://b.example"
        self.assertEqual(build_ranking_video._invidious_instances(),
                         ["https://a.example", "https://b.example"])

    def test_enabled_by_default(self):
        os.environ.pop("INVIDIOUS_DISABLED", None)
        self.assertTrue(build_ranking_video._invidious_enabled())

    def test_disabled_by_env_flag(self):
        for value in ("1", "true", "YES"):
            os.environ["INVIDIOUS_DISABLED"] = value
            self.assertFalse(build_ranking_video._invidious_enabled(), value)


class DownloadIntegrationTest(unittest.TestCase):
    """download() ordering: Invidious is a fast path that can never break the yt-dlp chain."""

    def setUp(self):
        self._saved = {k: os.environ.get(k)
                       for k in ("INVIDIOUS_DISABLED", "INVIDIOUS_INSTANCES", "YTDLP_PROXY",
                                 "YT_COOKIES_FILE", "YTDLP_MAX_HEIGHT")}
        os.environ.pop("INVIDIOUS_DISABLED", None)
        os.environ.pop("YTDLP_PROXY", None)
        os.environ.pop("YT_COOKIES_FILE", None)
        self.tmp = tempfile.mkdtemp(prefix="iv_fb_")
        self.out_base = os.path.join(self.tmp, "clip")
        # Never hit the network from the fallback or from the yt-dlp chain.
        self._patches = [
            mock.patch.object(build_ranking_video, "_download_via_invidious"),
            mock.patch.object(build_ranking_video, "_download_attempt"),
            mock.patch.object(build_ranking_video, "_resolve"),
        ]
        self.invidious, self.attempt, self.resolve = (p.start() for p in self._patches)

    def tearDown(self):
        for p in self._patches:
            p.stop()
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_successful_invidious_path_short_circuits_the_ytdlp_chain(self):
        produced = os.path.join(self.tmp, "clip.mp4")

        def make_file(url, out_base, timeout, deadline=None):
            # Mirrors the real fallback: the file only exists AFTER download() cleared partials
            # (pre-creating it here would be deleted by download()'s own glob cleanup).
            with open(produced, "wb") as handle:
                handle.write(b"not-really-video")
            return produced

        self.invidious.side_effect = make_file
        self.resolve.return_value = produced

        result = build_ranking_video.download(YOUTUBE_URL, self.out_base)

        self.assertEqual(result, produced)
        self.invidious.assert_called_once()
        self.attempt.assert_not_called()          # chain must not run once a source is fetched

    def test_invidious_failure_falls_through_to_the_ytdlp_chain(self):
        self.invidious.side_effect = RuntimeError("Invidious fallback failed: no instances")
        self.resolve.return_value = None
        # Make every yt-dlp route fail so download() raises with the aggregated report.
        self.attempt.side_effect = RuntimeError("Sign in to confirm you're not a bot")

        with self.assertRaises(RuntimeError) as ctx:
            build_ranking_video.download(YOUTUBE_URL, self.out_base)

        self.attempt.assert_called()              # chain DID run after the fallback failed
        self.assertIn("[invidious]", str(ctx.exception))
        self.assertIn("Sign in to confirm you're not a bot", str(ctx.exception))

    def test_disabled_flag_skips_the_fallback_entirely(self):
        os.environ["INVIDIOUS_DISABLED"] = "1"
        self.resolve.return_value = None
        self.attempt.side_effect = RuntimeError("bot-walled")

        with self.assertRaises(RuntimeError) as ctx:
            build_ranking_video.download(YOUTUBE_URL, self.out_base)

        self.invidious.assert_not_called()
        self.assertNotIn("[invidious]", str(ctx.exception))

    def test_non_youtube_url_never_consults_the_fallback(self):
        self.resolve.return_value = None
        self.attempt.side_effect = RuntimeError("nope")

        with self.assertRaises(RuntimeError):
            build_ranking_video.download(NON_YOUTUBE_URL, self.out_base)

        self.invidious.assert_not_called()

    def test_direct_media_url_still_short_circuits_before_any_route(self):
        # A direct .mp4 is fetched by the pre-existing fast path; no fallback, no chain.
        self.resolve.return_value = None
        with self.assertRaises(Exception):
            with mock.patch("urllib.request.urlopen") as urlopen:
                urlopen.side_effect = OSError("blocked")
                build_ranking_video.download("https://tenor.com/view/x.mp4", self.out_base)
        self.invidious.assert_not_called()
        self.attempt.assert_not_called()

    def test_error_report_names_the_cookie_when_no_session_is_present(self):
        """Total wall must still explain the missing cookie -- that hint is the operator's fix."""
        self.invidious.side_effect = RuntimeError("Invidious fallback failed: timeout")
        self.resolve.return_value = None
        self.attempt.side_effect = RuntimeError("Sign in to confirm you're not a bot")
        os.environ.pop("YT_COOKIES_FILE", None)

        with self.assertRaises(RuntimeError) as ctx:
            build_ranking_video.download(YOUTUBE_URL, self.out_base)

        message = str(ctx.exception)
        self.assertIn("all YouTube download routes failed", message)
        self.assertIn("YT_COOKIES", message)


class StreamToRangeTest(unittest.TestCase):
    """_stream_to must use Range requests (70x faster than a plain read) and chunk the file.

    A plain full-file read measured ~0.04 MB/s from a third-party IP while ranged requests
    held ~2.9 MB/s, so chunking is what makes a 715s source downloadable at all.
    """

    TOTAL = 10 * 1024 * 1024     # 10 MiB logical file served by the fake endpoint

    @staticmethod
    def _fake_endpoint(requests, fail_on_range=None):
        class FakeResp:
            def __init__(self, headers, payload):
                self.headers = headers
                self._payload = payload
            def read(self, *_args, **_kwargs):
                out, self._payload = self._payload, b""
                return out
            def __enter__(self):
                return self
            def __exit__(self, *_exc):
                return False

        def fake_urlopen(req, timeout=None):
            headers = {str(k).lower(): v for k, v in getattr(req, "headers", {}).items()}
            rng = headers.get("range")
            requests.append(rng)
            if fail_on_range is not None and rng == fail_on_range:
                raise OSError("simulated stall")
            if rng == "bytes=0-0":
                return FakeResp({"Content-Range": f"bytes 0-0/{StreamToRangeTest.TOTAL}"}, b"x")
            lo, hi = (int(p) for p in rng.split("=")[1].split("-"))
            return FakeResp({}, b"y" * (hi - lo + 1))

        return fake_urlopen

    def _stream(self, fail_on_range=None):
        requests = []
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "out.bin")
            with mock.patch("urllib.request.urlopen",
                            side_effect=self._fake_endpoint(requests, fail_on_range)):
                written = build_ranking_video._stream_to(
                    path, "https://rr1---sn-example.googlevideo.com/videoplayback", 5)
            with open(path, "rb") as handle:
                size = len(handle.read())
        return requests, written, size

    def test_probe_issues_a_one_byte_range_request(self):
        requests, _written, _size = self._stream()
        self.assertEqual(requests[0], "bytes=0-0")

    def test_file_is_assembled_from_sequential_range_chunks(self):
        requests, written, size = self._stream()
        # probe + ceil(10MiB / 4MiB) chunk requests
        self.assertEqual(len(requests), 1 + 3)
        self.assertEqual(written, self.TOTAL)
        self.assertEqual(size, self.TOTAL)
        self.assertTrue(all(r.startswith("bytes=") for r in requests[1:]))

    def test_stalled_chunk_is_retried_three_times_then_reported(self):
        with self.assertRaises(RuntimeError) as ctx:
            self._stream(fail_on_range="bytes=4194304-8388607")
        self.assertIn("failed after 3 tries", str(ctx.exception))


class _FakeResp:
    """Minimal urllib response double: headers + a one-shot body + context manager."""

    def __init__(self, headers, payload):
        self.headers = headers
        self._payload = payload

    def read(self, *_args, **_kwargs):
        out, self._payload = self._payload, b""
        return out

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


class InvidiousBodyTest(unittest.TestCase):
    """Exercises the REAL body of _download_via_invidious (previously 100% mocked, so an
    adversarial review proved a mutated API path escaped the suite). urlopen is faked so these
    stay offline: the instance API returns JSON, and googlevideo returns ranged bytes."""

    VIDEO_ITAG, AUDIO_ITAG = 137, 140
    VIDEO_BYTES = b"V" * (6 * 1024 * 1024)     # 6 MiB -> two 4 MiB ranged chunks
    AUDIO_BYTES = b"A" * (512 * 1024)

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="iv_body_")
        self.out_base = os.path.join(self.tmp, "clip")
        self._saved = {k: os.environ.get(k)
                       for k in ("INVIDIOUS_INSTANCES", "INVIDIOUS_DISABLED", "YTDLP_MAX_HEIGHT")}
        os.environ["INVIDIOUS_INSTANCES"] = "https://one.example,https://two.example"
        os.environ.pop("INVIDIOUS_DISABLED", None)
        os.environ.pop("YTDLP_MAX_HEIGHT", None)
        self.calls = []
        self._ffmpeg = mock.patch.object(build_ranking_video.subprocess, "run")
        self.ffmpeg = self._ffmpeg.start()

        def fake_ffmpeg(cmd, **kwargs):
            # Simulate a successful lossless remux by producing the merged file.
            # `out` is the last argument of the ffmpeg invocation.
            with open(cmd[-1], "wb") as handle:
                handle.write(b"M" * 16)
            return mock.Mock(returncode=0)

        self.ffmpeg.side_effect = fake_ffmpeg

    def tearDown(self):
        self._ffmpeg.stop()
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    @staticmethod
    def _payload(with_audio=True):
        video = [{"itag": InvidiousBodyTest.VIDEO_ITAG,
                  "type": 'video/mp4; codecs="avc1.640028"', "qualityLabel": "1080p",
                  "url": f"https://rr1---sn-example.googlevideo.com/videoplayback"
                         f"?itag={InvidiousBodyTest.VIDEO_ITAG}"}]
        audio = []
        if with_audio:
            audio = [{"itag": InvidiousBodyTest.AUDIO_ITAG,
                      "type": 'audio/mp4; codecs="mp4a.40.2"',
                      "url": f"https://rr1---sn-example.googlevideo.com/videoplayback"
                             f"?itag={InvidiousBodyTest.AUDIO_ITAG}"}]
        return {"title": "Shark Tank", "adaptiveFormats": video + audio}

    def _install_urlopen(self, payload, down_instances=()):
        def fake(req, timeout=None):
            url = getattr(req, "full_url", None) or str(req)
            headers = {str(k).lower(): v for k, v in getattr(req, "headers", {}).items()}
            rng = headers.get("range")
            self.calls.append((url, rng))
            if "/api/v1/videos/" in url:
                if any(broken in url for broken in down_instances):
                    raise OSError("instance down")
                return _FakeResp({}, json.dumps(payload).encode())
            body = (self.VIDEO_BYTES if f"itag={self.VIDEO_ITAG}" in url
                    else self.AUDIO_BYTES)
            if rng == "bytes=0-0":
                return _FakeResp({"Content-Range": f"bytes 0-0/{len(body)}"}, b"x")
            lo, hi = (int(p) for p in rng.split("=")[1].split("-"))
            return _FakeResp({}, body[lo:hi + 1])

        patcher = mock.patch("urllib.request.urlopen", side_effect=fake)
        self.addCleanup(patcher.stop)
        return patcher.start()

    def test_happy_path_merges_and_cleans_up(self):
        self._install_urlopen(self._payload())
        path = build_ranking_video._download_via_invidious(
            YOUTUBE_URL, self.out_base, 10)
        self.assertEqual(path, self.out_base + ".mp4")
        self.assertTrue(os.path.isfile(path))
        self.ffmpeg.assert_called_once()
        # Both temp files must be gone (finally runs before the caller receives the path).
        leftovers = [f for f in os.listdir(self.tmp) if f.endswith((".iv.video", ".iv.audio"))]
        self.assertEqual(leftovers, [])
        # ffmpeg got -c copy: a lossless remux, never a re-encode.
        cmd = self.ffmpeg.call_args[0][0]
        self.assertIn("-c", cmd)
        self.assertIn("copy", cmd)
        self.assertIn("-i", cmd)

    def test_no_audio_payload_fails_over_instead_of_shipping_video_only(self):
        """Defect fix: audio is required, so a video-only result must never be returned."""
        self._install_urlopen(self._payload(with_audio=False))
        with self.assertRaises(RuntimeError) as ctx:
            build_ranking_video._download_via_invidious(YOUTUBE_URL, self.out_base, 10)
        self.assertIn("no audio format", str(ctx.exception))
        self.assertFalse(os.path.isfile(self.out_base + ".mp4"))
        self.ffmpeg.assert_not_called()

    def test_first_instance_down_falls_through_to_the_second(self):
        self._install_urlopen(self._payload(), down_instances=("one.example",))
        path = build_ranking_video._download_via_invidious(YOUTUBE_URL, self.out_base, 10)
        self.assertTrue(os.path.isfile(path))
        self.assertTrue(any("one.example" in url for url, _ in self.calls))
        self.assertTrue(any("two.example" in url for url, _ in self.calls))

    def test_expired_deadline_makes_no_network_call_at_all(self):
        self._install_urlopen(self._payload())
        with self.assertRaises(RuntimeError) as ctx:
            build_ranking_video._download_via_invidious(
                YOUTUBE_URL, self.out_base, 10, deadline=time.monotonic() - 1)
        self.assertIn("deadline", str(ctx.exception))
        self.assertEqual(self.calls, [])          # nothing was even queried

    def test_malformed_instance_json_tries_the_next_instance(self):
        def fake(req, timeout=None):
            url = getattr(req, "full_url", None) or str(req)
            self.calls.append((url, None))
            if "one.example" in url:
                return _FakeResp({}, b"not json at all")
            return _FakeResp({}, json.dumps(self._payload()).encode())
        with mock.patch("urllib.request.urlopen", side_effect=fake):
            path = build_ranking_video._download_via_invidious(
                YOUTUBE_URL, self.out_base, 10)
        self.assertTrue(os.path.isfile(path))
        self.assertTrue(any("two.example" in url for url, _ in self.calls))


class DeadlineOrderingTest(unittest.TestCase):
    """The deadline must be claimed BEFORE the fallback so the Invidious attempt is charged
    against it -- originally it was computed after, leaving the fallback outside the budget."""

    def setUp(self):
        self._saved = {k: os.environ.get(k)
                       for k in ("INVIDIOUS_DISABLED", "YTDLP_DEADLINE_SEC", "YTDLP_PROXY",
                                 "YT_COOKIES_FILE")}
        os.environ.pop("INVIDIOUS_DISABLED", None)
        os.environ.pop("YTDLP_PROXY", None)
        os.environ.pop("YT_COOKIES_FILE", None)
        self.tmp = tempfile.mkdtemp(prefix="iv_dl_")
        self.out_base = os.path.join(self.tmp, "clip")
        self._patches = [
            mock.patch.object(build_ranking_video, "_download_via_invidious"),
            mock.patch.object(build_ranking_video, "_download_attempt"),
            mock.patch.object(build_ranking_video, "_resolve"),
        ]
        self.invidious, self.attempt, self.resolve = (p.start() for p in self._patches)
        self.attempt.side_effect = RuntimeError("bot-walled")
        self.resolve.return_value = None

    def tearDown(self):
        for p in self._patches:
            p.stop()
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_exhausted_deadline_skips_the_fallback_and_the_chain(self):
        # A deadline smaller than a single instant is already expired when download() starts.
        os.environ["YTDLP_DEADLINE_SEC"] = "0.000001"
        with self.assertRaises(RuntimeError) as ctx:
            build_ranking_video.download(YOUTUBE_URL, self.out_base)
        # The fallback is charged to the budget, so it is skipped rather than running free.
        self.invidious.assert_not_called()
        # The deadline is claimed up front, so the chain respects it too: no route burns time
        # after the budget is gone.
        self.attempt.assert_not_called()
        message = str(ctx.exception)
        self.assertIn("all YouTube download routes failed", message)
        self.assertIn("[invidious] no time left", message)

    def test_fallback_receives_the_deadline_value(self):
        os.environ["YTDLP_DEADLINE_SEC"] = "30"
        self.invidious.side_effect = RuntimeError("boom")
        with self.assertRaises(RuntimeError):
            build_ranking_video.download(YOUTUBE_URL, self.out_base)
        self.invidious.assert_called_once()
        _url, _out, _timeout, passed_deadline = self.invidious.call_args[0]
        self.assertIsInstance(passed_deadline, float)
        # Remaining budget must be ~30s, i.e. it is the shared deadline, not None/unbounded.
        self.assertGreater(passed_deadline - time.monotonic(), 25)
        self.assertLessEqual(passed_deadline - time.monotonic(), 31)


if __name__ == "__main__":
    unittest.main()
