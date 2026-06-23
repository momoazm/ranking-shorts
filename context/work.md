# My Work

## Brand
**MOMO** — my content brand. Logo and brand guidelines live in `automations/newsletter/brand/`
(each automation project also carries its own `brand/theme.json`). Branding is not optional:
load the brand assets, never re-derive colors/fonts.

## What I do
I create videos that get posted to **YouTube** (currently the MOMO Shorts channel —
Peter & Stewie AI "brainrot" Shorts). The plan is to grow into **multiple accounts with
different video types across as many social platforms as possible** (TikTok, Instagram, etc.).

## Revenue streams
- **None yet.** Pre-revenue. The long game is monetizing the content and/or selling the
  automations themselves.

## Tools I use day-to-day
- **Claude Code** — my main build environment / assistant (this folder)
- **Gemini** — secondary AI
- **YouTube, TikTok** — publishing platforms
- **Google Drive** — files (mostly on school days)
- **WhatsApp** — comms

## MCP servers connected
- **Firecrawl** — web search / scraping / extraction (primary web data provider)

## How the automations are organized (the WAT framework)
My automations follow a **Workflows / Agents / Tools** split: markdown SOPs in `workflows/`
describe the plan, deterministic Python scripts in `tools/` do the work, and the agent (you)
orchestrates. Each automation lives in `automations/<name>/` with its own rules `.md` file — read
it before working in that project. They all share one `API.env` at the repo root.
