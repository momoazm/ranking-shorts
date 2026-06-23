"""Generate an illustrative AI image from a text prompt.

Providers, tried in order with automatic fallback. The DEFAULT chain leads with
Gemini 2.5 Flash Image ("Nano Banana") because it is the only provider that accepts
reference images for *character consistency* (its headline strength) — essential when
every frame of a brainrot video must keep Peter & Stewie on-model. If the free Gemini
quota is exhausted (or the key is unset), it falls back to the existing free image chain:
Cloudflare Workers AI (FLUX.1-schnell) -> Hugging Face -> Pollinations.ai (keyless).

  gemini       : Nano Banana. Honors --refs (base64-inlined reference PNGs) for consistency.
  cloudflare   : FLUX.1-schnell, 10,000 free neurons/day.
  huggingface  : FLUX.1-schnell via HF Inference.
  pollinations : keyless last resort.

For character cutouts, prompt the subject on a plain solid white background, full body,
sticker style, so a later cutout step can flood-fill a clean transparent PNG.

Usage:
    python tools/generate_ai_image.py --prompt "a blue shark in sneakers" --out .tmp/art.png
    python tools/generate_ai_image.py --prompt "..." --provider gemini --refs a.png,b.png --out .tmp/s.png

Prints JSON: {"provider": "gemini"|"cloudflare"|"huggingface"|"pollinations", "path": "<out>"}
"""
import argparse
import base64
import os
import urllib.parse

from _common import load_env, emit, fail

# Nano Banana. Overridable in case the model id changes (it has churned through 2025-2026).
GEMINI_IMAGE_MODEL = os.environ.get("GEMINI_IMAGE_MODEL", "gemini-2.5-flash-image")


def _read_b64(path):
    with open(path, "rb") as f:
        return base64.b64encode(f.read()).decode("ascii")


def generate_gemini(prompt, out_path, refs=None):
    """Gemini 2.5 Flash Image (Nano Banana) via the REST generateContent endpoint.

    `refs` is an optional list of image paths inlined as reference images so the model
    keeps characters/style consistent across a whole video's worth of frames.
    """
    import httpx

    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("GEMINI_API_KEY not set")

    parts = [{"text": prompt}]
    for ref in (refs or []):
        if ref and os.path.isfile(ref):
            parts.append({"inline_data": {"mime_type": "image/png", "data": _read_b64(ref)}})

    url = (f"https://generativelanguage.googleapis.com/v1beta/models/"
           f"{GEMINI_IMAGE_MODEL}:generateContent")
    resp = httpx.post(
        url,
        headers={"x-goog-api-key": key, "Content-Type": "application/json"},
        json={"contents": [{"parts": parts}],
              "generationConfig": {"responseModalities": ["IMAGE"]}},
        timeout=120,
    )
    if resp.status_code == 429:
        raise RuntimeError("Gemini image quota/rate limit hit (429)")
    resp.raise_for_status()
    data = resp.json()

    candidates = data.get("candidates") or []
    if not candidates:
        # Surface safety blocks etc. so the caller can fall back instead of looping.
        raise RuntimeError(f"Gemini returned no candidates: {str(data)[:300]}")
    img_b64 = None
    for part in candidates[0].get("content", {}).get("parts", []):
        blob = part.get("inline_data") or part.get("inlineData")  # REST uses camelCase
        if blob and blob.get("data"):
            img_b64 = blob["data"]
            break
    if not img_b64:
        raise RuntimeError(f"Gemini response had no image part: {str(data)[:300]}")

    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "wb") as f:
        f.write(base64.b64decode(img_b64))


def generate_cloudflare(prompt, out_path, refs=None):
    import httpx

    api_token = os.environ.get("CLOUDFLARE_API_TOKEN")
    account_id = os.environ.get("CLOUDFLARE_ACCOUNT_ID")
    if not api_token or not account_id:
        raise RuntimeError("CLOUDFLARE_API_TOKEN / CLOUDFLARE_ACCOUNT_ID not set")

    url = f"https://api.cloudflare.com/client/v4/accounts/{account_id}/ai/run/@cf/black-forest-labs/flux-1-schnell"
    resp = httpx.post(
        url,
        headers={"Authorization": f"Bearer {api_token}"},
        json={"prompt": prompt, "steps": 8},
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()
    image_b64 = data.get("result", data).get("image")
    if not image_b64:
        raise RuntimeError(f"Cloudflare response had no image field: {data}")
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "wb") as f:
        f.write(base64.b64decode(image_b64))


def generate_huggingface(prompt, out_path, refs=None):
    import httpx

    api_key = os.environ.get("HF_API_TOKEN")
    if not api_key:
        raise RuntimeError("HF_API_TOKEN not set")

    resp = httpx.post(
        "https://router.huggingface.co/hf-inference/models/black-forest-labs/FLUX.1-schnell",
        headers={"Authorization": f"Bearer {api_key}"},
        json={"inputs": prompt, "parameters": {"width": 1024, "height": 1024}},
        timeout=120,
    )
    resp.raise_for_status()
    if not resp.headers.get("content-type", "").startswith("image/"):
        raise RuntimeError(f"Hugging Face did not return an image: {resp.text[:300]}")
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "wb") as f:
        f.write(resp.content)


def generate_pollinations(prompt, out_path, refs=None):
    import httpx

    encoded = urllib.parse.quote(prompt)
    url = f"https://image.pollinations.ai/prompt/{encoded}?width=1024&height=1024&nologo=true"
    resp = httpx.get(url, timeout=120)
    resp.raise_for_status()
    if not resp.headers.get("content-type", "").startswith("image/"):
        raise RuntimeError("Pollinations did not return an image")
    os.makedirs(os.path.dirname(out_path) or ".", exist_ok=True)
    with open(out_path, "wb") as f:
        f.write(resp.content)


# Ordered best-first. Gemini leads (consistency + free tier); the FLUX chain is the fallback.
PROVIDERS = {
    "gemini": generate_gemini,
    "cloudflare": generate_cloudflare,
    "huggingface": generate_huggingface,
    "pollinations": generate_pollinations,
}
DEFAULT_ORDER = ["gemini", "cloudflare", "huggingface", "pollinations"]
# FREE providers only — Nano Banana (gemini) has NO free tier (limit 0), so the free pipeline
# skips it entirely to avoid a guaranteed 429 on every call.
FREE_ORDER = ["cloudflare", "huggingface", "pollinations"]


def generate(prompt, out_path, provider=None, refs=None, style="", order=None):
    """Generate one image, returning (provider_name, errors_dict).

    order: explicit provider sequence (wins). Else a single `provider`. Else DEFAULT_ORDER.
    Raises RuntimeError with the collected per-provider errors if all attempts fail.
    """
    full_prompt = prompt + (style or "")
    seq = order if order else ([provider] if provider else DEFAULT_ORDER)
    errors = {}
    for name in seq:
        fn = PROVIDERS.get(name)
        if fn is None:
            errors[name] = "unknown provider"
            continue
        try:
            fn(full_prompt, out_path, refs=refs)
            return name, errors
        except Exception as e:
            errors[name] = str(e)
    raise RuntimeError(f"All image providers failed: {errors}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--provider", choices=list(PROVIDERS), help="Force one provider (default: fallback chain)")
    parser.add_argument("--refs", default="", help="Comma-separated reference image paths (gemini only)")
    parser.add_argument("--style", default="", help="Optional style suffix appended to the prompt")
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    load_env()
    refs = [p.strip() for p in args.refs.split(",") if p.strip()]
    try:
        name, errors = generate(args.prompt, args.out, provider=args.provider, refs=refs, style=args.style)
    except RuntimeError as e:
        fail(str(e))
        return
    emit({"provider": name, "path": args.out,
          **({"fallback_from": list(errors.keys())} if errors else {})})


if __name__ == "__main__":
    main()
