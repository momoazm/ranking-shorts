# MOMO's tracked Instagram accounts (baseline, 2026-07-01)

Both accounts are brand-new (near-zero followers, no confirmed live non-dry-run post yet per the
`ranking-shorts-instagram` memory). So Phase 1's job is prescriptive ("adopt winning patterns"),
not comparative.

## Account 1 — `@rank_ingshorts`
- Project: `ranking shorts` (core video engine).
- `IG_USER_ID=17841414896541039`. Publishes via Graph API (`upload_instagram.py`) or Zernio
  (`upload_zernio.py` — a "Switch Instagram posting to Zernio API" commit exists; confirm current).
- Format: faceless Top-N ranking Shorts, cross-posted from YouTube.

## Account 2 — `rankingshorts1`
- Project: `clipping-auto` (MrBeast-clip pipeline, daily).
- `IG_USER_ID=17841479158600540`. Same reusable Meta System User token, different IG_USER_ID.
- Format: MrBeast clip highlights.

## Known issue to fix in Phase 1
- **Cadence:** automation posts ~6×/day to these brand-new accounts (per memory). The 2026 Reels
  model penalizes feed-flooding — throttle to ≤1/day / 3–5 per week, strongest videos only.
