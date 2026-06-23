"""Extract clean article text from a URL for deeper research than search snippets give.

Tries Tavily Extract first, falls back to httpx + trafilatura. If the extracted
text is long, optionally cleans/condenses it via a fast LLM so the agent's own
(more expensive) reasoning step receives shorter, cleaner input. Cleaners are ordered
best-first — Groq -> Cerebras -> Gemini -> Mistral -> OpenRouter — and a provider that
errors or hits its rate limit is skipped for the next (each used only if its key is set);
if all of them fail it ships the raw extracted text rather than failing the call.

Usage:
    python tools/extract_article.py --url "https://..." [--clean-with-groq]

Prints JSON: {"provider": "tavily"|"trafilatura", "url": ..., "text": ..., "cleaned": bool}
"""
import argparse
import os

from _common import load_env, emit, fail

GROQ_CLEAN_THRESHOLD_CHARS = 6000

CLEAN_PROMPT = (
    "Strip boilerplate (nav/ads/cookie notices/bylines) from this scraped "
    "article and condense it to the key facts, figures, and quotes only. "
    "Plain text, no commentary:\n\n"
)


def extract_tavily(url):
    from tavily import TavilyClient

    api_key = os.environ.get("TAVILY_API_KEY")
    if not api_key:
        raise RuntimeError("TAVILY_API_KEY not set")

    client = TavilyClient(api_key=api_key)
    response = client.extract(urls=[url])
    results = response.get("results", [])
    if not results:
        raise RuntimeError("Tavily Extract returned no results for this URL")
    return results[0].get("raw_content", "")


def extract_trafilatura(url):
    import httpx
    import trafilatura

    resp = httpx.get(url, timeout=20, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0"})
    resp.raise_for_status()
    text = trafilatura.extract(resp.text)
    if not text:
        raise RuntimeError("trafilatura could not extract article text from this page")
    return text


def clean_with_groq(text):
    from groq import Groq

    api_key = os.environ.get("GROQ_API_KEY")
    if not api_key:
        raise RuntimeError("GROQ_API_KEY not set")

    client = Groq(api_key=api_key)
    completion = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": CLEAN_PROMPT + text}],
    )
    return completion.choices[0].message.content


def clean_with_gemini(text):
    """Fallback condenser using Gemini (Google AI Studio free tier) via the REST API.

    Recurring free tier (per-minute / per-day limits), so it fits the project's
    free-tier-first rule. Uses httpx (already a dep) — no extra SDK needed.
    """
    import httpx

    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        raise RuntimeError("GEMINI_API_KEY not set")

    model = os.environ.get("GEMINI_TEXT_MODEL", "gemini-2.5-flash")
    resp = httpx.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        params={"key": api_key},
        json={"contents": [{"parts": [{"text": CLEAN_PROMPT + text}]}]},
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()
    parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
    out = "".join(p.get("text", "") for p in parts).strip()
    if not out:
        raise RuntimeError(f"Gemini returned no text: {str(data)[:300]}")
    return out


def _openai_compatible_clean(text, base_url, key_env, default_model, model_env, extra_headers=None):
    """Shared condenser for any OpenAI-compatible /chat/completions endpoint.

    Cerebras, OpenRouter, and Mistral all speak this dialect — only the base URL,
    key env var, and default model differ. Each has a recurring free tier.
    """
    import httpx

    api_key = os.environ.get(key_env)
    if not api_key:
        raise RuntimeError(f"{key_env} not set")

    model = os.environ.get(model_env, default_model)
    headers = {"Authorization": f"Bearer {api_key}"}
    if extra_headers:
        headers.update(extra_headers)
    resp = httpx.post(
        f"{base_url}/chat/completions",
        headers=headers,
        json={"model": model, "messages": [{"role": "user", "content": CLEAN_PROMPT + text}]},
        timeout=60,
    )
    resp.raise_for_status()
    out = (resp.json()["choices"][0]["message"]["content"] or "").strip()
    if not out:
        raise RuntimeError(f"{key_env} returned empty content")
    return out


def clean_with_cerebras(text):
    return _openai_compatible_clean(
        text, "https://api.cerebras.ai/v1", "CEREBRAS_API_KEY", "gpt-oss-120b", "CEREBRAS_MODEL")


def clean_with_openrouter(text):
    return _openai_compatible_clean(
        text, "https://openrouter.ai/api/v1", "OPENROUTER_API_KEY",
        "meta-llama/llama-3.2-3b-instruct:free", "OPENROUTER_MODEL")


def clean_with_mistral(text):
    return _openai_compatible_clean(
        text, "https://api.mistral.ai/v1", "MISTRAL_API_KEY", "mistral-small-latest", "MISTRAL_MODEL")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", required=True)
    parser.add_argument("--clean-with-groq", action="store_true")
    args = parser.parse_args()

    load_env()

    try:
        text = extract_tavily(args.url)
        provider = "tavily"
    except Exception as tavily_error:
        try:
            text = extract_trafilatura(args.url)
            provider = "trafilatura"
        except Exception as fallback_error:
            fail(
                "Both Tavily Extract and trafilatura failed.",
                url=args.url,
                tavily_error=str(tavily_error),
                fallback_error=str(fallback_error),
            )
            return

    cleaned = False
    cleaner = None
    if args.clean_with_groq and len(text) > GROQ_CLEAN_THRESHOLD_CHARS:
        # Ordered best-first by quality + free-tier reliability; a provider that
        # errors or hits its rate limit is skipped for the next one.
        chain = (
            ("groq", clean_with_groq),          # fast, high-quality, generous free tier
            ("cerebras", clean_with_cerebras),  # very fast 120B, generous free tier
            ("gemini", clean_with_gemini),      # strong, solid daily free tier
            ("mistral", clean_with_mistral),    # capable small model
            ("openrouter", clean_with_openrouter),  # free models, tightest limits -> last
        )
        for name, fn in chain:
            try:
                text = fn(text)
                cleaned = True
                cleaner = name
                break
            except Exception:
                continue  # try next cleaner, then fall through with raw text

    emit({"provider": provider, "url": args.url, "text": text, "cleaned": cleaned, "cleaner": cleaner})


if __name__ == "__main__":
    main()
