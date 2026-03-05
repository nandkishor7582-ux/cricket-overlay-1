"""
LIVE CRICKET OBS OVERLAY — Cloud Web App
Deploy to Railway / Render / any cloud.

Uses Cricbuzz JSON API directly — no HTML scraping, much more reliable.
"""

import os, re, json, time, threading, logging, requests
from datetime import datetime
from flask import Flask, jsonify, request, render_template_string

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger(__name__)

app = Flask(__name__)
SCRAPE_INTERVAL = 3

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.cricbuzz.com/",
    "Accept-Language": "en-US,en;q=0.9",
}

_matches    = {}
_match_lock = threading.Lock()

def blank():
    return {
        "team1":   {"name":"","score":"","overs":"","flag_img":""},
        "team2":   {"name":"","score":"","overs":"","flag_img":""},
        "crr":"", "rrr":"", "target":"", "need":"", "partnership":"",
        "match_status":"LIVE", "yet_to_bat":"", "last_wicket":"",
        "current_over":0, "last_over_balls":[], "current_ball":"",
        "batsman1":{}, "batsman2":{}, "bowler":{},
        "match_format":"T20", "series_name":"", "last_updated":""
    }

def get_state(mid):
    with _match_lock:
        if mid not in _matches:
            _matches[mid] = {"data": blank(), "last_fetch": 0, "error": ""}
        return _matches[mid]

def fetch_miniscore(mid):
    url = f"https://www.cricbuzz.com/api/cricket-match/{mid}/miniscore"
    r = requests.get(url, headers=HEADERS, timeout=10)
    r.raise_for_status()
    return r.json()

def parse_miniscore(raw, prev):
    d = blank()
    # Keep previous team names/flags so they never blank out
    for k in ["team1","team2"]:
        for f in ["name","flag_img"]:
            if prev[k].get(f):
                d[k][f] = prev[k][f]
    try:
        ms  = raw.get("miniscore", raw)
        msd = ms.get("matchScoreDetails", {})
        hdr = raw.get("matchHeader", {})

        # Innings scores — most reliable source
        innings = msd.get("inningsScoreList", [])
        for i, inn in enumerate(innings):
            key = "team1" if i == 0 else "team2"
            name = (inn.get("batTeamName") or inn.get("teamName") or "").strip()
            if name: d[key]["name"] = name
            d[key]["score"] = f"{inn.get('score',0)}-{inn.get('wickets',0)}"
            d[key]["overs"] = str(inn.get("overs",""))

        # Team names from header (fills in bowling team name)
        t1n = (hdr.get("team1",{}).get("name") or hdr.get("team1",{}).get("shortName") or "").strip()
        t2n = (hdr.get("team2",{}).get("name") or hdr.get("team2",{}).get("shortName") or "").strip()
        if t1n and not d["team1"]["name"]: d["team1"]["name"] = t1n
        if t2n and not d["team2"]["name"]: d["team2"]["name"] = t2n

        # Also try batting/bowling team from miniscore root
        bat  = (ms.get("batTeamName") or ms.get("battingTeamName") or "").strip()
        bowl = (ms.get("bowlingTeamName") or ms.get("fieldingTeamName") or "").strip()
        if bat  and not d["team1"]["name"]: d["team1"]["name"] = bat
        if bowl and not d["team2"]["name"]: d["team2"]["name"] = bowl

        # Stats
        d["crr"]    = str(ms.get("currentRunRate") or "")
        d["rrr"]    = str(ms.get("requiredRunRate") or "")
        d["target"] = str(ms.get("target") or "")

        # Status
        status = (msd.get("customStatus") or ms.get("status") or
                  hdr.get("status") or "LIVE")
        d["match_status"] = str(status)[:60]

        d["last_wicket"] = str(ms.get("lastWicket") or "")

        ps = ms.get("partnerShip") or {}
        if ps: d["partnership"] = f"{ps.get('runs',0)}({ps.get('balls',0)})"

        tgt = int(ms.get("target") or 0)
        if tgt and innings:
            cur = int(innings[-1].get("score",0))
            if tgt - cur > 0: d["need"] = f"Need {tgt-cur} more runs"

        # Over balls
        recent = str(ms.get("recentOvsStats") or ms.get("recentBallsStats") or "")
        if recent.strip():
            balls = [b.strip().upper() for b in recent.strip().split() if b.strip()]
            d["last_over_balls"] = balls
            if balls: d["current_ball"] = balls[-1]
        d["current_over"] = int(ms.get("overNumber") or ms.get("ovrNum") or 0)

        # Batsmen
        bs  = ms.get("batsmanStriker") or {}
        bns = ms.get("batsmanNonStriker") or {}
        if bs.get("batName"):
            d["batsman1"] = {
                "name": bs["batName"], "runs": bs.get("batRuns",0),
                "balls": bs.get("batBalls",0), "fours": bs.get("batFours",0),
                "sixes": bs.get("batSixes",0), "sr": str(bs.get("batStrikeRate","0.00")),
                "on_strike": True, "photo": ""
            }
        if bns.get("batName"):
            d["batsman2"] = {
                "name": bns["batName"], "runs": bns.get("batRuns",0),
                "balls": bns.get("batBalls",0), "fours": bns.get("batFours",0),
                "sixes": bns.get("batSixes",0), "sr": str(bns.get("batStrikeRate","0.00")),
                "on_strike": False, "photo": ""
            }

        # Bowler
        bwl = ms.get("bowlerStriker") or ms.get("bowlerNonStriker") or {}
        if bwl.get("bowlName"):
            d["bowler"] = {
                "name": bwl["bowlName"], "overs": str(bwl.get("bowlOvs","0")),
                "maidens": bwl.get("bowlMaidens",0), "runs": bwl.get("bowlRuns",0),
                "wickets": bwl.get("bowlWkts",0), "economy": str(bwl.get("bowlEcon","0.00")),
                "photo": ""
            }

        fmt = (hdr.get("matchFormat") or hdr.get("matchType") or raw.get("matchType") or "")
        if fmt: d["match_format"] = str(fmt).upper()
        d["series_name"] = str(hdr.get("seriesName") or hdr.get("series") or "")[:80]

    except Exception as e:
        log.warning(f"parse error: {e}")

    d["last_updated"] = datetime.now().strftime("%H:%M:%S")
    return d

def scrape_loop(mid):
    log.info(f"[{mid}] Scraper started")
    errors = 0
    while True:
        try:
            state = get_state(mid)
            raw   = fetch_miniscore(mid)
            data  = parse_miniscore(raw, state["data"])
            with _match_lock:
                _matches[mid]["data"]       = data
                _matches[mid]["last_fetch"] = time.time()
                _matches[mid]["error"]      = ""
            t1 = data["team1"]; t2 = data["team2"]
            log.info(f"[{mid}] {t1.get('name','?')} {t1.get('score','?')} "
                     f"vs {t2.get('name','?')} {t2.get('score','?')} "
                     f"CRR={data.get('crr','?')}")
            errors = 0
        except Exception as e:
            errors += 1
            log.warning(f"[{mid}] Error #{errors}: {e}")
            with _match_lock:
                if mid in _matches: _matches[mid]["error"] = str(e)
            if errors >= 5:
                time.sleep(30); errors = 0
        time.sleep(SCRAPE_INTERVAL)

_threads = {}
def ensure_scraper(mid):
    if mid not in _threads or not _threads[mid].is_alive():
        t = threading.Thread(target=scrape_loop, args=(mid,), daemon=True)
        t.start(); _threads[mid] = t

@app.route("/")
def index():
    return render_template_string(INDEX_HTML)

@app.route("/overlay")
def overlay():
    mid = re.sub(r'[^\d]','', request.args.get("match",""))
    if not mid: return "Missing ?match=ID", 400
    ensure_scraper(mid)
    with open(os.path.join(os.path.dirname(__file__), "livematch.html"), encoding="utf-8") as f:
        html = f.read()
    # Point fetch to our data API
    html = html.replace(
        "fetch('data.json?t='+Date.now(),{cache:'no-store'})",
        f"fetch('/data/{mid}?t='+Date.now(),{{cache:'no-store'}})"
    )
    # Also inject current data immediately so overlay shows on first load
    state = get_state(mid)
    init_data = json.dumps(state["data"])
    html = html.replace(
        "// Python server replaces this line with actual JSON each page load:\n// window.__LIVE_DATA = {...};   ← injected by /overlay route",
        f"// Live data injected at page load:\ntry{{ const _d={init_data}; setTimeout(()=>{{ lastData=_d; applyData(_d); }}, 100); }}catch(e){{}}"
    )
    return html

@app.route("/data/<mid>")
def data_api(mid):
    mid = re.sub(r'[^\d]','', mid)
    if not mid: return jsonify({}), 400
    ensure_scraper(mid)
    state = get_state(mid)
    resp = jsonify(state["data"])
    resp.headers["Cache-Control"] = "no-store"
    resp.headers["Access-Control-Allow-Origin"] = "*"
    return resp

@app.route("/debug/<mid>")
def debug(mid):
    mid = re.sub(r'[^\d]','', mid)
    ensure_scraper(mid)
    s = get_state(mid); d = s["data"]
    last = datetime.fromtimestamp(s['last_fetch']).strftime('%H:%M:%S') if s['last_fetch'] else 'never'
    return (f"<html><head><meta charset='UTF-8'><style>"
            f"body{{background:#05080f;color:#eee;font-family:monospace;padding:20px;}}"
            f"h2{{color:#FFD700;}}.ok{{color:#00ff88;}}.err{{color:#ff4444;}}"
            f"pre{{background:#0a1628;padding:16px;border-radius:8px;font-size:13px;overflow:auto;}}"
            f"</style></head><body>"
            f"<h2>🏏 Match {mid}</h2>"
            f"<p>Last fetch: {last} | Error: <span class='err'>{s.get('error','none')}</span></p>"
            f"<p class='ok'>{d['team1'].get('name','?')} {d['team1'].get('score','?')} ({d['team1'].get('overs','?')} ov)</p>"
            f"<p class='ok'>{d['team2'].get('name','?')} {d['team2'].get('score','?')} ({d['team2'].get('overs','?')} ov)</p>"
            f"<p>CRR:{d.get('crr','?')} RRR:{d.get('rrr','?')} Status:{d.get('match_status','?')}</p>"
            f"<p>Bat1:{d.get('batsman1',{{}}).get('name','?')} Bat2:{d.get('batsman2',{{}}).get('name','?')} Bowl:{d.get('bowler',{{}}).get('name','?')}</p>"
            f"<h2>Full JSON</h2><pre>{json.dumps(d, indent=2)}</pre></body></html>")

@app.route("/status")
def status():
    with _match_lock:
        out = {}
        for mid, s in _matches.items():
            d = s["data"]
            out[mid] = {"t1":d["team1"].get("name","?"),"s1":d["team1"].get("score","?"),
                        "t2":d["team2"].get("name","?"),"s2":d["team2"].get("score","?"),
                        "crr":d.get("crr","?"),"err":s["error"],
                        "last": datetime.fromtimestamp(s["last_fetch"]).strftime("%H:%M:%S") if s["last_fetch"] else "never"}
    return jsonify(out)

INDEX_HTML = """<!DOCTYPE html><html lang="en"><head>
<meta charset="UTF-8"><title>🏏 Cricket Overlay</title>
<style>*{box-sizing:border-box;margin:0;padding:0}
body{background:#05080f;color:#fff;font-family:'Segoe UI',sans-serif;min-height:100vh;display:flex;align-items:center;justify-content:center;}
.card{background:#0a1628;border:2px solid #FF6B00;border-radius:16px;padding:40px 48px;width:520px;max-width:95vw;}
h1{font-size:28px;color:#FFD700;margin-bottom:6px;}
.sub{color:rgba(255,255,255,.5);font-size:14px;margin-bottom:28px;}
label{font-size:13px;color:rgba(255,215,0,.8);font-weight:700;letter-spacing:1px;display:block;margin-bottom:8px;}
input{width:100%;background:rgba(255,255,255,.07);border:1px solid rgba(255,255,255,.2);border-radius:8px;color:#fff;font-size:20px;padding:12px 16px;outline:none;margin-bottom:20px;}
input:focus{border-color:#FF6B00;}
.btn{width:100%;background:linear-gradient(90deg,#FF6B00,#FFD700);color:#000;font-weight:900;font-size:16px;padding:14px;border:none;border-radius:8px;cursor:pointer;}
.links{margin-top:16px;display:none;gap:8px;flex-wrap:wrap;}
.lbtn{flex:1;text-align:center;padding:9px;border-radius:6px;font-size:12px;font-weight:700;text-decoration:none;letter-spacing:1px;min-width:100px;}
.tip{margin-top:20px;font-size:12px;color:rgba(255,255,255,.35);line-height:1.7;}
code{color:#FFD700;}
</style></head><body>
<div class="card">
  <h1>🏏 Cricket OBS Overlay</h1>
  <div class="sub">Live scores via Cricbuzz JSON API · Updates every 3s</div>
  <label>CRICBUZZ MATCH ID OR URL</label>
  <input id="mid" placeholder="12345  or paste full Cricbuzz URL" autocomplete="off">
  <button class="btn" onclick="go()">▶ OPEN OVERLAY</button>
  <div class="links" id="links">
    <a class="lbtn" id="obsLink" href="#" target="_blank" style="background:rgba(0,176,255,.15);color:#00B0FF;border:1px solid rgba(0,176,255,.3);">📺 OBS Source</a>
    <a class="lbtn" id="prevLink" href="#" target="_blank" style="background:rgba(255,107,0,.15);color:#FF6B00;border:1px solid rgba(255,107,0,.3);">🔍 Preview</a>
    <a class="lbtn" id="dbgLink" href="#" target="_blank" style="background:rgba(0,255,100,.1);color:#00ff88;border:1px solid rgba(0,255,100,.3);">🐛 Debug</a>
  </div>
  <div class="tip">
    <b style="color:rgba(255,215,0,.6)">Get Match ID from Cricbuzz URL:</b><br>
    <code>cricbuzz.com/live-cricket-scores/<b>12345</b>/india-vs-pakistan...</code><br><br>
    <b style="color:rgba(255,215,0,.6)">OBS:</b> Add Browser Source → paste overlay URL → 1280×720
  </div>
</div>
<script>
document.getElementById('mid').addEventListener('keydown',e=>{if(e.key==='Enter')go();});
function go(){
  const raw=document.getElementById('mid').value.trim();
  const m=raw.match(/\d+/);
  if(!m){alert('Enter a match ID or Cricbuzz URL');return;}
  const id=m[0], base=window.location.origin;
  document.getElementById('obsLink').href=document.getElementById('prevLink').href=base+'/overlay?match='+id;
  document.getElementById('dbgLink').href=base+'/debug/'+id;
  document.getElementById('links').style.display='flex';
}
</script></body></html>"""

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    log.info(f"Starting on port {port}")
    app.run(host="0.0.0.0", port=port, threaded=True)
