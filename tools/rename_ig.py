"""Rename the ranking/momoclips Instagram account's @username via the web UI (no API exists).

Interactive + gated. Opens a HEADFUL browser; Moemen makes the RIGHT account active (switch or
log in), then this fills the new username. --dry-run stops before saving (screenshot only);
--confirm actually saves. Loads the follower-race IG session as a starting point (accounts are
linked) so usually only an account SWITCH is needed, not a fresh login. Saves the reached session
to this project's own state file so a later --confirm run skips the switch.

    python tools/rename_ig.py --new itsmomoclips --expect-account rank_ingshorts --dry-run
    python tools/rename_ig.py --new itsmomoclips --expect-account rank_ingshorts --confirm

Prints one JSON object. Never stores a password. This is a one-time public identity change --
run it on Moemen's PC with him present.
"""
import argparse
import os
import re
import sys
import time
from collections import Counter
from pathlib import Path

from _common import emit, fail, REPO_ROOT

FR_SESSION = REPO_ROOT.parent / "follower-race" / "state" / "ig_session.json"
RK_SESSION = REPO_ROOT / "state" / "ig_session.json"
EDIT_URL = "https://www.instagram.com/accounts/edit/"
HOME_URL = "https://www.instagram.com/"
LOGIN_URL = "https://www.instagram.com/accounts/login/"


def log(*a):
    print("[rename_ig]", *a, file=sys.stderr, flush=True)


def active_account(page):
    try:
        alts = page.eval_on_selector_all(
            "img[alt*='profile picture' i]",
            "els => els.map(e => e.getAttribute('alt'))") or []
        names = [re.match(r"(.+?)'s profile picture", a or "", re.I).group(1).lower()
                 for a in alts if re.match(r"(.+?)'s profile picture", a or "", re.I)]
        return Counter(names).most_common(1)[0][0] if names else None
    except Exception:
        return None


def find_username_input(page):
    for sel in ("input[name='username']", "input[aria-label*='sername' i]",
                "input[aria-describedby*='username' i]"):
        el = page.query_selector(sel)
        if el:
            return el
    return None


def main():
    from playwright.sync_api import sync_playwright
    ap = argparse.ArgumentParser()
    ap.add_argument("--new", default=None, help="New @username (without @). Not needed for --capture-only.")
    ap.add_argument("--expect-account", default="rank_ingshorts",
                    help="The account whose handle we're changing (must be ACTIVE before we edit)")
    ap.add_argument("--dry-run", action="store_true", help="Fill but DO NOT save (screenshot only)")
    ap.add_argument("--confirm", action="store_true", help="Actually save the new username")
    ap.add_argument("--fresh", action="store_true",
                    help="Start from a BLANK browser (ignore saved sessions) so you can log into an "
                         "account that isn't linked in the switcher.")
    ap.add_argument("--capture-only", action="store_true",
                    help="Just log in + SAVE the session for this account, then stop (no rename).")
    ap.add_argument("--browser", default="edge", choices=["edge", "chromium"],
                    help="Which browser to drive (default edge -> installed Microsoft Edge).")
    ap.add_argument("--edge-profile", action="store_true",
                    help="Drive Moemen's REAL signed-in Edge profile (already logged into IG). "
                         "Edge must be fully CLOSED first (the profile locks while it runs).")
    ap.add_argument("--edge-profile-dir", default="Default",
                    help="Which Edge profile folder to use (Default, 'Profile 1', ...).")
    ap.add_argument("--wait-seconds", type=int, default=300)
    args = ap.parse_args()

    new = (args.new or "").lstrip("@").strip().lower()
    expect = args.expect_account.lstrip("@").lower()
    if not args.capture_only:
        if not re.fullmatch(r"[a-z0-9._]{2,30}", new):
            fail(f"'{new}' is not a valid IG username."); return
        if not (args.dry_run or args.confirm):
            fail("Pass --dry-run (fill only) or --confirm (save)."); return

    if args.fresh:
        start_session = None
    else:
        start_session = RK_SESSION if RK_SESSION.exists() else (FR_SESSION if FR_SESSION.exists() else None)
    shot = str(REPO_ROOT / ".tmp" / "ig_rename.png")
    Path(shot).parent.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as pw:
        browser = None
        if args.edge_profile:
            # Drive Moemen's real signed-in Edge profile so his existing IG login is reused (no
            # re-login). Requires Edge closed. Persistent context = login lives on disk in the
            # profile, so a window close doesn't lose it.
            user_data = Path(os.environ["LOCALAPPDATA"]) / "Microsoft" / "Edge" / "User Data"
            if not user_data.exists():
                fail(f"Edge profile dir not found at {user_data}"); return
            try:
                ctx = pw.chromium.launch_persistent_context(
                    str(user_data), channel="msedge", headless=False,
                    args=[f"--profile-directory={args.edge_profile_dir}"], no_viewport=True)
            except Exception as e:
                msg = str(e)
                hint = ("Close ALL Microsoft Edge windows first (the profile is locked while Edge "
                        "runs), then re-run.") if ("ProcessSingleton" in msg or "lock" in msg.lower()
                                                   or "Target page" in msg) else ""
                fail(f"Could not open your Edge profile: {msg[:200]}", hint=hint); return
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
            first_url = HOME_URL   # already logged in -> go straight to the app
        else:
            launch_kw = {"headless": False}
            if args.browser == "edge":
                launch_kw["channel"] = "msedge"   # installed Edge, fresh context (not the live profile)
            browser = pw.chromium.launch(**launch_kw)
            ctx = (browser.new_context(storage_state=str(start_session)) if start_session
                   else browser.new_context())
            page = ctx.new_page()
            first_url = LOGIN_URL if (args.fresh or not start_session) else HOME_URL

        def shutdown():
            try:
                (browser.close() if browser else ctx.close())
            except Exception:
                pass

        page.goto(first_url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3000)

        # 1) Make sure the RIGHT account is active. Poll (Moemen switches/logs in the open window).
        log(f"A browser opened. Make @{expect} the ACTIVE Instagram account (switch accounts or log "
            f"in). Waiting up to {args.wait_seconds}s...")
        waited = 0
        while waited < args.wait_seconds:
            try:
                acct = active_account(page)
            except Exception:
                # Page/tab may have navigated or been closed mid-login; re-acquire from context.
                if ctx.pages:
                    page = ctx.pages[-1]
                    acct = None
                else:
                    break
            if acct == expect:
                log(f"@{expect} is active.")
                break
            if acct:
                log(f"(currently @{acct} -- switch to @{expect})")
            try:
                page.wait_for_timeout(4000)
            except Exception:
                if ctx.pages:
                    page = ctx.pages[-1]
                else:
                    break
            waited += 4
        try:
            acct = active_account(page)
        except Exception:
            acct = None
        if acct != expect:
            try:
                page.screenshot(path=shot)
            except Exception:
                shot = None
            shutdown()
            fail(f"@{expect} never became active (saw @{acct}). Re-run with it active.",
                 screenshot=shot); return

        RK_SESSION.parent.mkdir(parents=True, exist_ok=True)
        ctx.storage_state(path=str(RK_SESSION))   # persist so --confirm skips the switch

        if args.capture_only:
            shutdown()
            emit({"status": "session_saved", "account": acct, "session": str(RK_SESSION),
                  "note": "Logged in and saved. Re-run without --capture-only to rename."})
            return

        # 2) Open Edit Profile and read the current username.
        page.goto(EDIT_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(4000)
        inp = find_username_input(page)
        if not inp:
            page.screenshot(path=shot); shutdown()
            fail("Could not find the username field on Edit Profile.", screenshot=shot); return
        current = (inp.input_value() or "").strip()

        # 3) Fill the new username.
        inp.click()
        inp.fill("")
        inp.type(new, delay=40)
        page.wait_for_timeout(2500)
        body = (page.content() or "").lower()
        taken = ("not available" in body or "isn't available" in body or "username isn't available" in body)
        page.screenshot(path=shot)

        if taken:
            shutdown()
            fail(f"Instagram says @{new} isn't available.", current=current, screenshot=shot); return

        if args.dry_run:
            shutdown()
            emit({"status": "dry_run", "account": acct, "current_username": current,
                  "new_username": new, "available": True, "screenshot": shot,
                  "note": "Filled but NOT saved. Re-run with --confirm to save."})
            return

        # 4) --confirm: click Submit/Save, handle any confirmation dialog, verify.
        saved = False
        for sel in ("div[role='button']:has-text('Submit')", "button:has-text('Submit')",
                    "button[type='submit']", "div[role='button']:has-text('Save')",
                    "button:has-text('Save')"):
            el = page.query_selector(sel)
            if el:
                el.click(); saved = True; break
        page.wait_for_timeout(2500)
        # confirmation modal ("Change username?") -> confirm
        for sel in ("button:has-text('Yes')", "button:has-text('Confirm')",
                    "div[role='button']:has-text('Change')", "button:has-text('Change')"):
            el = page.query_selector(sel)
            if el:
                el.click(); break
        page.wait_for_timeout(4000)
        page.goto(EDIT_URL, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(4000)
        inp2 = find_username_input(page)
        now = (inp2.input_value() or "").strip() if inp2 else ""
        ctx.storage_state(path=str(RK_SESSION))
        page.screenshot(path=shot)
        shutdown()

        if now.lower() == new:
            emit({"status": "renamed", "account": acct, "from": current, "to": now,
                  "clicked_submit": saved, "screenshot": shot})
        else:
            fail(f"Save attempted but username reads '{now}', not '{new}'. Check the window/screenshot.",
                 clicked_submit=saved, screenshot=shot)


if __name__ == "__main__":
    main()
