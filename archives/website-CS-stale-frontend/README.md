# Archived: stale MOMO-site front-end (2026-07-01)

These four files (`index.html`, `api/`, `vercel.json`, `middleware.mjs`) used to live in
`projects/website/CS/`, but they were a **stale, divergent copy** of the MOMO site and never
deployed anything.

The **live site deploys from the `momoazm/CS` GitHub repo** (working clone at
`c:/Users/monar/Downloads/CS-deploy`): `website/index.html` is the page, `api/*.py` are the
Vercel serverless functions. That copy was ahead of this one (e.g. its calendar had already
dropped the admin password and gained recurring events, which this `index.html` never had).

Kept here (not deleted) per the repo's "don't delete — archive" rule, in case any snippet is
ever useful. **Do not edit these to change the live site** — edit `CS-deploy` and push.

`middleware.mjs` was a site-wide Basic Auth gate drafted on 2026-07-01 but never deployed (the
site is already private behind Vercel's own login).
