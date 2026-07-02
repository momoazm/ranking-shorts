// Vercel Routing Middleware: gates the WHOLE site (static page + every /api/* function)
// behind a single shared HTTP Basic Auth login. Runs on every route by default (no
// framework here, so no package.json -- .mjs avoids needing one). Browsers cache the
// credential per-origin after the first prompt, so each of Moemen's devices only has to
// enter it once.
//
// Set in Vercel: SITE_AUTH_PASSWORD (required). Username is fixed to "momo" -- only the
// password matters since just one person is meant to have it.

const USER = "momo";

export default function middleware(request) {
  const pass = process.env.SITE_AUTH_PASSWORD;
  if (!pass) {
    return new Response("Site auth not configured (SITE_AUTH_PASSWORD missing in Vercel).", { status: 500 });
  }

  const auth = request.headers.get("authorization") || "";
  if (auth.startsWith("Basic ")) {
    const decoded = atob(auth.slice(6));
    const sep = decoded.indexOf(":");
    const u = decoded.slice(0, sep);
    const p = decoded.slice(sep + 1);
    if (u === USER && p === pass) return; // continue to the requested resource
  }

  return new Response("Authentication required.", {
    status: 401,
    headers: { "WWW-Authenticate": 'Basic realm="MOMO", charset="UTF-8"' },
  });
}
