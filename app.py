"""
LIVE CRICKET OBS OVERLAY — Cloud Web App
=========================================
Deploy to Railway / Render / any cloud.
No Python on your PC needed.

Usage:
  Open in browser: https://your-app.railway.app/overlay?match=12345
  OBS Browser Source: same URL, 1280x720

Match ID: the number from cricbuzz.com URL
  https://www.cricbuzz.com/live-cricket-scores/[12345]/...
"""

import os, re, json, time, threading, logging
from datetime import datetime
from flask import Flask, jsonify, request, send_from_directory, render_template_string, Response

# ── Import all scraper logic from scraper_core ──────────────────────────────
from scraper_core import (
    parse, blank_data, fetch_page, load_photo_cache,
    _photo_cache, _photo_lock, save_photo_cache,
    SCRAPE_INTERVAL
)

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger(__name__)

app = Flask(__name__, static_folder="static")

# ── Per-match state ──────────────────────────────────────────────────────────
_matches   = {}   # match_id -> {"data": {...}, "last_fetch": float, "error": str}
_match_lock = threading.Lock()

SCRAPE_INTERVAL = 4   # seconds between fetches per match

def get_or_create_match(match_id: str) -> dict:
    with _match_lock:
        if match_id not in _matches:
            _matches[match_id] = {
                "data": blank_data(),
                "last_fetch": 0,
                "error": "",
                "fetching": False,
            }
        return _matches[match_id]

def scrape_match(match_id: str):
    """Background thread: keeps fetching a match every SCRAPE_INTERVAL seconds."""
    url = f"https://m.cricbuzz.com/cricket-commentary/{match_id}"
    log.info(f"[{match_id}] Scraper thread started → {url}")
    errors = 0
    while True:
        try:
            state = get_or_create_match(match_id)
            html  = fetch_page(url)
            data  = parse(html, state["data"])
            data["last_updated"] = datetime.now().strftime("%H:%M:%S")
            with _match_lock:
                _matches[match_id]["data"]       = data
                _matches[match_id]["last_fetch"]  = time.time()
                _matches[match_id]["error"]       = ""
            t1 = data["team1"]; t2 = data["team2"]
            log.info(f"[{match_id}] {t1.get('name','?')} {t1.get('score','?')} vs "
                     f"{t2.get('name','?')} {t2.get('score','?')} | "
                     f"CRR={data.get('crr','?')}")
            errors = 0
        except Exception as e:
            errors += 1
            log.warning(f"[{match_id}] Error ({errors}): {e}")
            with _match_lock:
                if match_id in _matches:
                    _matches[match_id]["error"] = str(e)
            if errors >= 5:
                log.warning(f"[{match_id}] 5 errors — sleeping 15s")
                time.sleep(15); errors = 0
        time.sleep(SCRAPE_INTERVAL)

_scraper_threads = {}  # match_id -> Thread

def ensure_scraper(match_id: str):
    """Start a scraper thread for this match if not already running."""
    if match_id not in _scraper_threads or not _scraper_threads[match_id].is_alive():
        t = threading.Thread(target=scrape_match, args=(match_id,), daemon=True)
        t.start()
        _scraper_threads[match_id] = t
        log.info(f"[{match_id}] Started scraper thread")

# ── Routes ───────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    """Landing page — enter a match ID."""
    return render_template_string(INDEX_HTML)

@app.route("/overlay")
def overlay():
    """The OBS overlay page. ?match=12345"""
    match_id = request.args.get("match", "").strip()
    m = re.search(r'\d+', match_id)
    if not m:
        return "Missing ?match=ID parameter. Example: /overlay?match=12345", 400
    match_id = m.group()
    ensure_scraper(match_id)
    # Serve the overlay HTML with the match_id baked in
    with open(os.path.join(os.path.dirname(__file__), "livematch.html"), encoding="utf-8") as f:
        html = f.read()
    # Patch the data.json fetch URL to use our API endpoint
    html = html.replace(
        "fetch('data.json?t='+Date.now())",
        f"fetch('/data/{match_id}?t='+Date.now())"
    )
    return html

@app.route("/data/<match_id>")
def data_endpoint(match_id):
    """JSON endpoint polled by the overlay every 2s."""
    match_id = re.sub(r'[^\d]', '', match_id)
    if not match_id:
        return jsonify({}), 400
    ensure_scraper(match_id)
    state = get_or_create_match(match_id)
    resp = jsonify(state["data"])
    resp.headers["Cache-Control"] = "no-store"
    resp.headers["Access-Control-Allow-Origin"] = "*"
    return resp

@app.route("/status")
def status():
    """Shows all active matches."""
    with _match_lock:
        info = {}
        for mid, state in _matches.items():
            d = state["data"]
            info[mid] = {
                "team1": d["team1"].get("name","?"),
                "team2": d["team2"].get("name","?"),
                "score1": d["team1"].get("score","?"),
                "score2": d["team2"].get("score","?"),
                "crr": d.get("crr","?"),
                "last_fetch": datetime.fromtimestamp(state["last_fetch"]).strftime("%H:%M:%S") if state["last_fetch"] else "never",
                "error": state["error"],
            }
    return jsonify(info)

# ── Landing page HTML ─────────────────────────────────────────────────────────

INDEX_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>🏏 Live Cricket Overlay</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#05080f;color:#fff;font-family:'Segoe UI',sans-serif;min-height:100vh;display:flex;align-items:center;justify-content:center;}
.card{background:#0a1628;border:2px solid #FF6B00;border-radius:16px;padding:40px 48px;width:520px;max-width:95vw;}
h1{font-size:28px;color:#FFD700;margin-bottom:6px;letter-spacing:1px;}
.sub{color:rgba(255,255,255,.5);font-size:14px;margin-bottom:28px;}
label{font-size:13px;color:rgba(255,215,0,.8);font-weight:700;letter-spacing:1px;display:block;margin-bottom:8px;}
input{width:100%;background:rgba(255,255,255,.07);border:1px solid rgba(255,255,255,.2);border-radius:8px;color:#fff;font-size:20px;padding:12px 16px;outline:none;margin-bottom:20px;}
input:focus{border-color:#FF6B00;}
.btn{width:100%;background:linear-gradient(90deg,#FF6B00,#FFD700);color:#000;font-weight:900;font-size:16px;letter-spacing:1px;padding:14px;border:none;border-radius:8px;cursor:pointer;}
.btn:hover{opacity:.9;}
.tip{margin-top:20px;font-size:12px;color:rgba(255,255,255,.35);line-height:1.6;}
.tip b{color:rgba(255,215,0,.6);}
.links{margin-top:16px;display:flex;gap:10px;}
.lbtn{flex:1;text-align:center;padding:8px;border-radius:6px;font-size:12px;font-weight:700;text-decoration:none;letter-spacing:1px;}
.obs{background:rgba(0,176,255,.15);color:#00B0FF;border:1px solid rgba(0,176,255,.3);}
.preview{background:rgba(255,107,0,.15);color:#FF6B00;border:1px solid rgba(255,107,0,.3);}
</style>
</head>
<body>
<div class="card">
  <h1>🏏 Cricket OBS Overlay</h1>
  <div class="sub">Live scores · Player photos · Auto-updating</div>
  <form onsubmit="go(event)">
    <label>CRICBUZZ MATCH ID OR URL</label>
    <input id="mid" placeholder="e.g. 12345  or paste full cricbuzz URL" autocomplete="off">
    <button class="btn" type="submit">▶ OPEN OVERLAY</button>
  </form>
  <div class="links" id="links" style="display:none">
    <a class="lbtn obs" id="obsLink" href="#" target="_blank">📺 Open in OBS</a>
    <a class="lbtn preview" id="previewLink" href="#" target="_blank">🔍 Preview in Browser</a>
  </div>
  <div class="tip">
    <b>How to get Match ID:</b><br>
    Go to cricbuzz.com → find your match → copy the number from the URL<br>
    <code style="color:#FFD700">cricbuzz.com/live-cricket-scores/<b>12345</b>/india-vs...</code><br><br>
    <b>OBS setup:</b> Add Browser Source → paste the overlay URL → set 1280×720
  </div>
</div>
<script>
function go(e) {
  e.preventDefault();
  const raw = document.getElementById('mid').value.trim();
  const m = raw.match(/\\d+/);
  if(!m) { alert('Please enter a match ID or Cricbuzz URL'); return; }
  const id = m[0];
  const url = window.location.origin + '/overlay?match=' + id;
  document.getElementById('obsLink').href = url;
  document.getElementById('previewLink').href = url;
  document.getElementById('links').style.display = 'flex';
}
</script>
</body>
</html>"""

# ── Startup ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    load_photo_cache()
    port = int(os.environ.get("PORT", 8000))
    log.info(f"Starting on port {port}")
    app.run(host="0.0.0.0", port=port, threaded=True)
