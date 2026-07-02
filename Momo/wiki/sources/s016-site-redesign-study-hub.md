---
type: source
tags: [momo]
updated: 2026-07-02
---
# s016 — Site redesign: 5 pages, Gumball-only, 9618 study hub, always-push

[[momo-website]] rebuilt from one long page into **5 pages** (index / oracle / study /
calendar / pipelines) with shared `assets/`, calmer motion, and **only** the animated
Gumball mascot (supersedes [[gumball-companions]]'s 4-character auto-attach). New
**Study hub**: 9618 syllabus tracker, SM-2-lite flashcards, past-paper timer,
pomodoro + streak — all localStorage, zero backend. Pushed live (momoazm/CS `b44eebb`).
New [[site-update-skill]] owns the build→verify→push flow + architecture map.
**Rule change:** websites are now **always pushed** once verified (supersedes
preview-before-push; other public actions still gated) — see `decisions/log.md` 2026-07-02.
Files → `C:\Users\monar\Downloads\CS-deploy\website\` · skill → `projects/website/skills/site-update/SKILL.md`
