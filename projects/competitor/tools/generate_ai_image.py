"""Generate an illustrative AI image from a text prompt, trying free-tier providers
in quality order with automatic fallback: Cloudflare Workers AI (FLUX.1-schnell, 10,000
free neurons/day, resets daily) -> Hugging Face Inference Providers -> Gemini
(gemini-2.5-flash-image, Google AI Studio free tier, when GEMINI_API_KEY is set) ->
Pollinations.ai (keyless, always-on last resort).

Freepik/Magnific was deliberately dropped from this chain: verified that its "free"
offering is a fixed one-time signup credit grant (~$5), not a recurring daily/monthly
allotment, so it doesn't fit this project's free-tier-first, never-runs-dry philosophy.
(Note: Imagen *on Vertex AI* is paid-only, but Gemini image generation via the AI Studio
API does have a recurring daily free tier — that's the one wired in here as a fallback.)

Every prompt gets a brand-style suffix from brand/theme.json so AI art stays visually
consistent with the rest of the newsletter.

Usage:
    python tools/generate_ai_image.py --prompt "a pharaoh studying a glowing scroll" --out .tmp/art1.png

Prints JSON: {"provider": "cloudflare"|"huggingface"|"gemini"|"pollinations", "path": "<out path>"}
"""
import argparse
import base64
import os
import urllib.parse

from _common import load_env, load_theme, emit, fail

BRAND_STYLE_SUFFIX = (
    ", in a gold, deep navy, and maroon Egyptian-emblem aesthetic, "
    "polished and modern, subtle scarab/pharaoh motifs, premium editorial illustration style"
)


def generate_cloudflare(prompt, out_path):
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
    # Cloudflare wraps most endpoints in {"result": {...}, "success": true}, but
    # handle the unwrapped shape too in case that envelope isn't present here.
    image_b64 = data.get("result", data).get("image")
    if not image_b64:
        raise RuntimeError(f"Cloudflare response had no image field: {data}")

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "wb") as f:
        f.write(base64.b64decode(image_b64))


def generate_huggingface(prompt, out_path):
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
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "wb") as f:
        f.write(resp.content)


def generate_gemini(prompt, out_path):
    import httpx

    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not set")

    model = os.environ.get("GEMINI_IMAGE_MODEL", "gemini-2.5-flash-image")
    resp = httpx.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        params={"key": api_key},
        json={
            "contents": [{"parts": [{"text": prompt}]}],
            "generationConfig": {"responseModalities": ["IMAGE"]},
        },
        timeout=120,
    )
    resp.raise_for_status()
    data = resp.json()
    parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
    image_b64 = None
    for part in parts:
        blob = part.get("inlineData") or part.get("inline_data")
        if blob and blob.get("data"):
            image_b64 = blob["data"]
            break
    if not image_b64:
        raise RuntimeError(f"Gemini response had no image data: {str(data)[:300]}")

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "wb") as f:
        f.write(base64.b64decode(image_b64))


def generate_pollinations(prompt, out_path):
    import httpx

    encoded = urllib.parse.quote(prompt)
    url = f"https://image.pollinations.ai/prompt/{encoded}?width=1024&height=1024&nologo=true"
    resp = httpx.get(url, timeout=60)
    resp.raise_for_status()
    if not resp.headers.get("content-type", "").startswith("image/"):
        raise RuntimeError("Pollinations did not return an image")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "wb") as f:
        f.write(resp.content)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()

    load_env()
    load_theme()  # validates brand/theme.json is present even though we only need the style suffix here
    full_prompt = args.prompt + BRAND_STYLE_SUFFIX

    providers = [
        ("cloudflare", generate_cloudflare),
        ("huggingface", generate_huggingface),
        ("gemini", generate_gemini),
        ("pollinations", generate_pollinations),
    ]
    errors = {}
    for name, fn in providers:
        try:
            fn(full_prompt, args.out)
            emit({"provider": name, "path": args.out, **({"fallback_from": list(errors.keys())} if errors else {})})
            return
        except Exception as e:
            errors[name] = str(e)

    fail("All image providers failed (Cloudflare, Hugging Face, Gemini, Pollinations).", errors=errors)


if __name__ == "__main__":
    main()
