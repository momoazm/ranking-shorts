---
name: extract-article
description: Use when Moemen has a URL (or a search result) and needs the full clean article text pulled out of the page — reading, quoting, or drafting copy from a specific source.
---

# Extract Article (scrape full text)

Pull clean readable text from a web page, best provider first.

## Provider order
1. **Tavily extract** — `python tools/extract_article.py --url "..."` (run from `projects/<name>/`).
2. **trafilatura** — automatic local fallback inside the tool if Tavily errors/limits.
3. **Groq cleanup** — optional pass (`GROQ_API_KEY`) to tidy the extracted text.

Surface a whole-chain failure before retrying.

## Notes
- The tool prints one JSON object to stdout; parse it (success → exit 0, failure → `{"error": ...}`).
- Scraped text often has odd characters — that's expected; don't strip the ASCII-escape fallback.
- To find the URL first, use the **research** skill.
