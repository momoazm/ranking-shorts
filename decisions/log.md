# Decision Log

Append-only. When a meaningful decision is made, log it here.

Format: [YYYY-MM-DD] DECISION: ... | REASONING: ... | CONTEXT: ...

---

[2026-06-23] DECISION: Replaced the `competitor` WAT project with an inline skill `compare-youtube-channels`, and archived the project to `archives/competitor/`. | REASONING: The full PDF/email pipeline was overkill for what's actually wanted — a decision-ready, in-chat comparison of MOMO vs rival YouTube channels. An inline skill keeps it lightweight, leans on existing tools (newsletter's toolset) and the Firecrawl→Tavily→Exa research chain, and avoids a whole project + venv. Also corrected the stale niche: the skill targets MOMO's real niche (faceless ranking/Top-N Shorts), not the old "AI cinematic" framing in the dead profile. | CONTEXT: User chose inline skill / MOMO-vs-competitors / in-chat output. Competitor's tools were duplicated in newsletter/, so nothing was lost. Repointed Gmail-token reuse hints in clipping-auto + ranking shorts from `competitor/token.json` to `newsletter/token.json`. Archived (not deleted) per the house "don't delete — archive" rule.

[2026-06-23] DECISION: Brand refresh — brighter gold (`#C9A96C`→`#FFD23F`) and way-darker navy (`#0B1622`→`#040810`); recolored `logo.png` + `brandguidelines.png` and made the logo background transparent. | REASONING: Moemen asked for a more vivid gold and a much darker blue, and to remove the logo's dark box (it showed as a black rectangle on dark backgrounds, e.g. the infographic footer). | CONTEXT: Updated master `brand/theme.json` (colors + button/icon gold refs) and re-synced all project `brand/` copies. Logo + guidelines recolored via additive gold/navy anchor shifts (preserving shading); logo bg flood-filled to transparent. Originals archived in `archives/brand-old/`.
