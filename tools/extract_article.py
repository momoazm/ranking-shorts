"""Extract clean article text from a URL for deeper research than search snippets give.

Tries Tavily Extract first, falls back to httpx + trafilatura. If the extracted
text is long, optionally cleans/condenses it via Groq's free-tier fast LLM so the
agent's own (more expensive) reasoning step receives shorter, cleaner input.

Usage:
    python tools/extract_article.py --url "https://..." [--clean-with-groq]

Prints JSON: {"provider": "tavily"|"trafilatura", "url": ..., "text": ..., "cleaned": bool}
"""
import argparse
import os

from _common import load_env, emit, fail

GROQ_CLEAN_THRESHOLD_CHARS = 6000


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
        model=os.environ.get("GROQ_MODEL", "openai/gpt-oss-120b"),
        messages=[
            {
                "role": "user",
                "content": (
                    "Strip boilerplate (nav/ads/cookie notices/bylines) from this scraped "
                    "article and condense it to the key facts, figures, and quotes only. "
                    "Plain text, no commentary:\n\n" + text
                ),
            }
        ],
    )
    return completion.choices[0].message.content


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
    if args.clean_with_groq and len(text) > GROQ_CLEAN_THRESHOLD_CHARS:
        try:
            text = clean_with_groq(text)
            cleaned = True
        except Exception:
            pass  # fall through with raw extracted text rather than failing the whole call

    emit({"provider": provider, "url": args.url, "text": text, "cleaned": cleaned})


if __name__ == "__main__":
    main()
