"""Search the web for a topic via Tavily, falling back to Exa if Tavily errors
or its free-tier quota is exhausted.

Usage:
    python tools/tavily_search.py --query "topic to research" [--max-results 5] [--topic news]

Prints JSON: {"provider": "tavily"|"exa", "query": ..., "results": [{"title","url","snippet","score"}, ...]}
"""
import argparse
import os

from _common import load_env, emit, fail


def search_tavily(query, max_results, topic):
    from tavily import TavilyClient

    api_key = os.environ.get("TAVILY_API_KEY")
    if not api_key:
        raise RuntimeError("TAVILY_API_KEY not set")

    client = TavilyClient(api_key=api_key)
    response = client.search(query=query, max_results=max_results, topic=topic)
    results = [
        {
            "title": r.get("title"),
            "url": r.get("url"),
            "snippet": r.get("content"),
            "score": r.get("score"),
        }
        for r in response.get("results", [])
    ]
    return results


def search_exa(query, max_results):
    from exa_py import Exa

    api_key = os.environ.get("EXA_API_KEY")
    if not api_key:
        raise RuntimeError("EXA_API_KEY not set")

    exa = Exa(api_key=api_key)
    response = exa.search_and_contents(query, num_results=max_results, text={"max_characters": 500})
    results = [
        {
            "title": r.title,
            "url": r.url,
            "snippet": getattr(r, "text", None),
            "score": getattr(r, "score", None),
        }
        for r in response.results
    ]
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--query", required=True)
    parser.add_argument("--max-results", type=int, default=5)
    parser.add_argument("--topic", default="general", choices=["general", "news"])
    args = parser.parse_args()

    load_env()

    try:
        results = search_tavily(args.query, args.max_results, args.topic)
        emit({"provider": "tavily", "query": args.query, "results": results})
        return
    except Exception as tavily_error:
        tavily_err_msg = str(tavily_error)

    try:
        results = search_exa(args.query, args.max_results)
        emit({
            "provider": "exa",
            "query": args.query,
            "results": results,
            "note": f"Tavily failed, fell back to Exa. Tavily error: {tavily_err_msg}",
        })
        return
    except Exception as exa_error:
        fail(
            "Both Tavily and Exa failed.",
            tavily_error=tavily_err_msg,
            exa_error=str(exa_error),
        )


if __name__ == "__main__":
    main()
