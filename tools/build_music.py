"""Generate the ranking account's original, rights-safe audio bed.

The old ranking bed was copied from a third-party video and pitch-shifted to try to avoid
fingerprinting. That is not a rights strategy. This script creates a small, unobtrusive synth
bed locally on every runner; it is mixed under original clip audio with ducking and never used
for standalone streamer clips.
"""
import os

from _common import REPO_ROOT, emit, fail
from _media import run_ffmpeg


def main():
    out_dir = REPO_ROOT / ".tmp" / "audio"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / "momo_pulse.mp3"
    duration = 120
    sample_rate = 44100
    cmd = [
        "-f", "lavfi", "-i", f"sine=frequency=82:duration={duration}:sample_rate={sample_rate}",
        "-f", "lavfi", "-i", f"sine=frequency=164:duration={duration}:sample_rate={sample_rate}",
        "-f", "lavfi", "-i", f"sine=frequency=246:duration={duration}:sample_rate={sample_rate}",
        "-filter_complex",
        "[0:a]volume=0.34[a0];[1:a]volume=0.18[a1];[2:a]volume=0.10[a2];"
        "[a0][a1][a2]amix=inputs=3:normalize=0[mix];"
        "[mix]lowpass=f=2600,highpass=f=55,apulsator=hz=0.11,"
        "aecho=0.8:0.55:90:0.16,afade=t=in:d=2,"
        f"afade=t=out:st={duration - 4}:d=4,volume=28.0,"
        "alimiter=limit=0.90[out]",
        "-map", "[out]", "-ac", "2", "-ar", str(sample_rate),
        "-c:a", "libmp3lame", "-b:a", "128k",
        "-metadata", "title=MOMO Original Pulse", "-metadata", "artist=MOMO",
        "-y", str(out),
    ]
    try:
        run_ffmpeg(cmd)
    except Exception as exc:
        fail(f"Could not generate rights-safe ranking bed: {exc}")
        return
    emit({"path": str(out), "bytes": os.path.getsize(out), "rights_policy": "generated_only"})


if __name__ == "__main__":
    main()
