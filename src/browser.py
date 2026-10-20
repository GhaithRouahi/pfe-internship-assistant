import json, random, time, urllib.request
from playwright.sync_api import sync_playwright
from .config import CFG, ROOT

CDP_URL = "http://127.0.0.1:9222"
AGENT_STATE = ROOT / "data" / "agent" / "tab.json"


def pause(kind="action"):
    lo, hi = CFG[{"job": "delay_between_jobs_sec", "page": "delay_between_pages_sec"}.get(kind, "delay_between_actions_sec")]
    time.sleep(random.uniform(lo, hi))


def _close_owned_tabs():
    """LinkedIn's anti-bot iframes sometimes freeze Chrome's debug connection. Closing the tabs Claude opened
    (never the user's own tabs) unfreezes it; the offer is simply reopened afterwards."""
    try:
        st = json.loads(AGENT_STATE.read_text())
        owned = set(st.get("owned") or []) | ({st["target"]} if st.get("target") else set())
    except Exception:
        owned = set()
    n = 0
    for t in json.load(urllib.request.urlopen(CDP_URL + "/json/list", timeout=5)):
        if t.get("type") == "page" and t.get("id") in owned:
            try:
                urllib.request.urlopen(f"{CDP_URL}/json/close/{t['id']}", timeout=5).read()
                n += 1
            except Exception:
                pass
    return n


def launch():
    """Attach to YOUR running Chrome (started with start_chrome.bat). The bot never sees or types your credentials:
    it just clicks in the window where you are already logged in."""
    pw = sync_playwright().start()
    err = None
    for attempt in range(2):
        try:
            browser = pw.chromium.connect_over_cdp(CDP_URL, timeout=30000 if attempt == 0 else 45000)
            return pw, browser.contexts[0]
        except Exception as e:
            err = e
            if attempt == 0:
                try:
                    print(f"(Chrome debug connection froze - closed {_close_owned_tabs()} of Claude's own tab(s), retrying)")
                except Exception:
                    pass
    pw.stop()
    raise SystemExit("Cannot attach to Chrome on port 9222 (" + type(err).__name__ + "). If start_chrome.bat is running, close any tab "
                     "stuck on a dialog and retry; otherwise close all Chrome windows, run start_chrome.bat, then retry.")


def shutdown(pw):
    pw.stop()   # disconnects only; your Chrome window stays open
