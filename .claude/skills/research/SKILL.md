---
name: research
description: Use when Moemen needs facts, sources, news, or background gathered from the web — looking something up, researching a topic, finding references for content, or checking what's current.
---

# Research (web search)

Gather information from the web, best provider first, fall back on limit/error.

## Provider order
1. **Firecrawl (MCP)** — `firecrawl_search` (richest results + page content). Default.
2. **Tavily** — `python tools/tavily_search.py --query "..."` (run from the relevant `projects/<name>/` folder; uses `TAVILY_API_KEY`).
3. **Exa** — automatic fallback inside the search tool (`EXA_API_KEY`) if Tavily errors/limits.

Only report failure if the **whole chain** is exhausted — don't loop silently.

## Output
- Summarize findings tight: answer first, then sources (title + URL).
- For pulling the full text of a specific article, hand off to the **extract-article** skill.

> Keys live in the gitignored `API.env`. After a Firecrawl search, call `firecrawl_search_feedback` with the search ID.
