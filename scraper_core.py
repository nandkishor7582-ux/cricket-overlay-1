"""
LIVE CRICKET OBS OVERLAY v19.0
- Scrapes m.cricbuzz.com (no Selenium)
- Photos: fetched via Cricbuzz search API + cached permanently
- Port 8000 → livematch.html + data.json
"""

import re, json, time, threading, http.server, socketserver, os, requests
from datetime import datetime
from bs4 import BeautifulSoup

SCRAPE_INTERVAL = 3
PORT_MAIN       = 8000
PHOTO_CACHE_FILE = "player_photos.json"   # persists across restarts

HEADERS_MOB = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 12; Pixel 6) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Mobile Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept": "text/html,application/xhtml+xml,*/*;q=0.8",
    "Referer": "https://m.cricbuzz.com/",
}
HEADERS_API = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Referer": "https://www.cricbuzz.com/",
}

SESSION = requests.Session()
SESSION.headers.update(HEADERS_MOB)

# ─── Photo cache ──────────────────────────────────────────────────────────────

_photo_cache = {}   # name -> photo_url  (in-memory + persisted to file)
_photo_lock  = threading.Lock()

def load_photo_cache():
    global _photo_cache
    try:
        if os.path.exists(PHOTO_CACHE_FILE):
            with open(PHOTO_CACHE_FILE, "r") as f:
                _photo_cache = json.load(f)
            print(f"  Loaded {len(_photo_cache)} cached player photos.")
    except: pass

def save_photo_cache():
    try:
        with open(PHOTO_CACHE_FILE, "w") as f:
            json.dump(_photo_cache, f, indent=2)
    except: pass

def get_photo(name: str) -> str:
    """Return photo URL for player name. Checks cache first, then fetches."""
    if not name or len(name) < 3:
        return ""
    with _photo_lock:
        if name in _photo_cache:
            return _photo_cache[name]

    url = fetch_photo_url(name)

    with _photo_lock:
        _photo_cache[name] = url
        save_photo_cache()
    return url

def fetch_photo_url(name: str) -> str:
    """
    Fetch player photo URL. Priority:
    1. Use profile_id + slug from embedded JSON (if available) → scrape profile page
    2. Cricbuzz search API
    3. Profile page scrape
    """
    try:
        # Priority 1: we have the slug from miniscore JSON
        if name in _player_slug_cache:
            prof_id, slug = _player_slug_cache[name]
            url = _scrape_profile_photo(prof_id, slug)
            if url: return url

        # Priority 2: Cricbuzz search API
        query = name.strip().lower().replace(" ", "+")
        api_url = f"https://www.cricbuzz.com/api/cricket-search/v2/search?query={query}&start=0&limit=5"
        r = requests.get(api_url, headers=HEADERS_API, timeout=8)
        r.raise_for_status()
        data = r.json()

        results = data.get("results", []) or data.get("entity", []) or []

        for item in results:
            itype = str(item.get("type","")).lower()
            if itype != "player": continue
            title = item.get("title","") or item.get("name","")
            if not _names_match(name, title): continue

            image_id = (item.get("imageId") or item.get("faceImageId") or
                        item.get("imgId")   or item.get("id"))
            slug = item.get("slug") or _name_to_slug(name)
            if image_id:
                return f"https://static.cricbuzz.com/a/img/v1/i1/c{image_id}/{slug}.jpg?d=high&p=gthumb"

        # Priority 3: profile page scrape
        for item in results:
            if str(item.get("type","")).lower() != "player": continue
            pid = item.get("id") or item.get("playerId")
            slug = item.get("slug") or _name_to_slug(name)
            if pid:
                return _scrape_profile_photo(pid, slug)

    except Exception:
        pass
    return ""

def _scrape_profile_photo(pid, slug):
    """Scrape the player profile page to get their photo."""
    try:
        url = f"https://www.cricbuzz.com/profiles/{pid}/{slug}"
        r = requests.get(url, headers=HEADERS_API, timeout=8)
        soup = BeautifulSoup(r.text, "html.parser")
        # Profile page has: <img src="https://static.cricbuzz.com/a/img/v1/i1/c{CID}/{slug}.jpg?...">
        for img in soup.find_all("img"):
            src = img.get("src","")
            if "gthumb" in src or "p=det" in src:
                if slug.split("-")[0] in src or slug.split("-")[-1] in src:
                    return src.replace("d=low","d=high")
        # Any img with the player slug
        for img in soup.find_all("img"):
            src = img.get("src","")
            if slug[:4] in src and "cricbuzz" in src:
                return src.replace("d=low","d=high")
    except: pass
    return ""

def _names_match(a, b):
    """Fuzzy name match — last name or full name."""
    a, b = a.lower().strip(), b.lower().strip()
    if a == b: return True
    a_parts = a.split(); b_parts = b.split()
    # last name match
    if a_parts and b_parts and a_parts[-1] == b_parts[-1]: return True
    # first word match + one more word
    if len(a_parts) >= 2 and len(b_parts) >= 2:
        if a_parts[0] == b_parts[0] and a_parts[1][0] == b_parts[1][0]: return True
    return False

def _name_to_slug(name):
    return re.sub(r'[^a-z0-9]+', '-', name.lower().strip()).strip('-')

# Background photo fetcher — fetches photos async so scraper isn't blocked
def fetch_photos_async(names):
    def _fetch():
        for name in names:
            if name and name not in _photo_cache:
                get_photo(name)
    threading.Thread(target=_fetch, daemon=True).start()

# ─── HTTP Server ──────────────────────────────────────────────────────────────

def safe_int(v):
    try: return int(re.sub(r'[^\d]', '', str(v)) or '0')
    except: return 0

def fetch_page(url):
    r = SESSION.get(url, timeout=10)
    r.raise_for_status()
    return r.text

def blank_data():
    return {
        "team1":    {"name":"","score":"","overs":"","flag_img":"","flag_manual":""},
        "team2":    {"name":"","score":"","overs":"","flag_img":"","flag_manual":""},
        "crr":"", "rrr":"", "target":"", "need":"", "partnership":"",
        "match_status":"LIVE", "yet_to_bat":"", "last_wicket":"",
        "current_over":0, "last_over_balls":[], "current_ball":"",
        "batsman1":{}, "batsman2":{}, "bowler":{},
        "match_format":"T20", "series_name":"",
        "last_updated":""
    }

def load_manual_flags():
    try:
        if os.path.exists("data.json"):
            with open("data.json","r") as f:
                d = json.load(f)
            return (d.get("team1",{}).get("flag_manual",""),
                    d.get("team2",{}).get("flag_manual",""))
    except: pass
    return "",""

# ─── Miniscore JSON extractor ─────────────────────────────────────────────────

_player_slug_cache = {}  # name -> (profile_id, slug)

def _nv(script, key):
    """Extract numeric value from double-escaped Next.js JSON string."""
    m = re.search(r'[\\]*"' + re.escape(key) + r'[\\]*"\s*:\s*([\d.]+)', script)
    return m.group(1) if m else ""

def _sv(script, key):
    """Extract short string value from double-escaped Next.js JSON string."""
    # Matches: \"key\":\"VALUE\" with various levels of escaping
    m = re.search(r'(?:\\+)"' + re.escape(key) + r'(?:\\+)"\s*:\s*(?:\\+)"([^\\]{1,100})(?:\\+)"', script)
    if m: return m.group(1)
    m2 = re.search(r'"' + re.escape(key) + r'"\s*:\s*"([^"]{1,100})"', script)
    return m2.group(1) if m2 else ""

def _extract_player(script, key):
    """Extract a player object (batsmanStriker, bowlerStriker etc) from miniscore JSON."""
    # Find the key in script, then extract the object content after it
    idx = script.find(key)
    if idx < 0: return None
    chunk = script[idx:idx+800]
    def nv(k): return _nv(chunk, k)
    def sv(k): return _sv(chunk, k)
    name = sv("name")
    if not name: return None
    pid_m = re.search(r'(?:\\+)"id(?:\\+)"\s*:\s*(\d+)', chunk)
    pid   = pid_m.group(1) if pid_m else ""
    slug_m = re.search(r'/profiles/(\d+)/([a-z0-9-]+)', chunk)
    slug  = slug_m.group(2) if slug_m else _name_to_slug(name)
    prof_id = slug_m.group(1) if slug_m else pid
    return {
        "name": name, "pid": pid, "prof_id": prof_id, "slug": slug,
        "runs": safe_int(nv("runs")),
        "balls": safe_int(nv("balls")),
        "fours": safe_int(nv("fours")),
        "sixes": safe_int(nv("sixes")),
        "sr": sv("strikeRate") or (f"{safe_int(nv('runs'))*100/max(1,safe_int(nv('balls'))):.2f}"),
        "overs": nv("overs") or nv("overs"),
        "maidens": safe_int(nv("maidens")),
        "economy": nv("economy"),
        "wickets": safe_int(nv("wickets")),
        "photo": ""
    }

def _extract_miniscore_json(html):
    """
    Parse the self.__next_f.push script that Cricbuzz inlines live match data into.
    Returns dict with: crr, rrr, target, pship, status, lastWkt, bat1, bat2, bowl, player_slugs
    """
    # Find the script containing 'miniscore' and 'currentRunRate'
    best_script = ""
    for sm in re.finditer(r'<script[^>]*>(.*?)</script>', html, re.DOTALL):
        content = sm.group(1)
        if 'currentRunRate' in content and 'miniscore' in content:
            if len(content) > len(best_script):
                best_script = content
    if not best_script:
        return None

    s = best_script
    result = {}

    # CRR / RRR / target
    result["crr"]    = _nv(s, "currentRunRate")
    result["rrr"]    = _nv(s, "requiredRunRate")
    result["target"] = _nv(s, "target")

    # Partnership
    pb_m = re.search(r'partnerShip.{0,40}?balls.{0,10}?:(\d+).{0,40}?runs.{0,10}?:(\d+)', s)
    if not pb_m:
        pb_m = re.search(r'partnerShip.{0,40}?runs.{0,10}?:(\d+).{0,40}?balls.{0,10}?:(\d+)', s)
        if pb_m: result["pship"] = f"{pb_m.group(1)}({pb_m.group(2)})"
    else:
        result["pship"] = f"{pb_m.group(2)}({pb_m.group(1)})"

    # Status — customStatus is most reliable
    cs_idx = s.find("customStatus")
    if cs_idx >= 0:
        cs_chunk = s[cs_idx:cs_idx+200]
        # Double-escaped: customStatus\\\":\"India won by 5 wkts\\\"
        cs_m = re.search(r'customStatus[^:]*:([^,}{]{2,80})', cs_chunk)
        if cs_m:
            val = cs_m.group(1).strip().replace('\\"','').replace('\\\\','').replace('"','').replace("'","").strip()
            if val and len(val) > 2: result["status"] = val

    # lastWicket
    lw_idx = s.find("lastWicket")
    if lw_idx >= 0:
        lw_chunk = s[lw_idx:lw_idx+300]
        # Pattern: lastWicket\\\":\"VALUE\\\",
        lw_m = re.search(r'lastWicket[^:]*:[^"]*"([^"\\]{5,150})', lw_chunk)
        if not lw_m:
            # Try extracting between pairs of escaped quotes
            lw_m = re.search(r'lastWicket.{0,10}:(.{5,150})(?=,\s*\\\\"|,\s*"rem)', lw_chunk)
        if lw_m:
            val = lw_m.group(1).replace('\\\\"','').replace('\\"','').replace('\\\\','').replace('"','').strip()
            if val and len(val) > 4: result["lastWkt"] = val[:100]

    # Batsmen
    bat1 = _extract_player(s, "batsmanStriker")
    bat2 = _extract_player(s, "batsmanNonStriker")

    # Bowler — prefer bowlerNonStriker (the one who just bowled the current over)
    bowl = _extract_player(s, "bowlerNonStriker") or _extract_player(s, "bowlerStriker")

    if bat1: result["bat1"] = {"name":bat1["name"],"runs":bat1["runs"],"balls":bat1["balls"],"fours":bat1["fours"],"sixes":bat1["sixes"],"sr":bat1["sr"],"photo":""}
    if bat2: result["bat2"] = {"name":bat2["name"],"runs":bat2["runs"],"balls":bat2["balls"],"fours":bat2["fours"],"sixes":bat2["sixes"],"sr":bat2["sr"],"photo":""}
    if bowl: result["bowl"] = {"name":bowl["name"],"overs":bowl["overs"],"maidens":bowl["maidens"],"runs":bowl["runs"],"wickets":bowl["wickets"],"economy":bowl["economy"],"photo":""}

    # Collect player slugs for photo lookup
    slugs = {}
    for p in [bat1, bat2, bowl]:
        if p and p.get("name") and p.get("prof_id") and p.get("slug"):
            slugs[p["name"]] = (p["prof_id"], p["slug"])
    result["player_slugs"] = slugs

    return result

# ─── Parser ───────────────────────────────────────────────────────────────────

def parse(html, data):
    soup = BeautifulSoup(html, "html.parser")
    full = soup.get_text(" ", strip=True)

    # ── Title / series ────────────────────────────────────────────────────────
    title_el = soup.find("title")
    if title_el:
        t = re.sub(r'(?i)cricket commentary\s*\|\s*', '', title_el.get_text(strip=True)).strip()
        if t: data["series_name"] = t[:80]

    # ── Match format ──────────────────────────────────────────────────────────
    for fmt in ["T20I","T20","ODI","Test","T10"]:
        if re.search(r'\b' + fmt + r'\b', full, re.I):
            data["match_format"] = fmt.upper(); break

    # ── Status ────────────────────────────────────────────────────────────────
    # Only short clean result — never capture long commentary descriptions
    st_found = ""
    r1 = re.search(r'([A-Z][a-zA-Z\s]{2,20}?\s+won by\s+\d+\s+(?:wkts?|runs?)[^<\n,]{0,20})', full)
    if r1: st_found = r1.group(1).strip()
    if not st_found:
        r2 = re.search(r'\b(Innings Break|Rain Delay|Stumps|Match Drawn|Match Tied)\b', full, re.I)
        if r2: st_found = r2.group(1).strip()
    if not st_found: st_found = "LIVE"
    data["match_status"] = re.sub(r'\s+', ' ', st_found).strip()[:50]

    # ── NAME → PHOTO map from profile links on page ──────────────────────────
    page_photos = {}
    for a in soup.find_all("a", href=True):
        if "/profiles/" not in a["href"]: continue
        img = a.find("img")
        if not img: continue
        src = img.get("src","")
        if not src or ("gthumb" not in src and "p=det" not in src): continue
        name = a.get_text(strip=True)
        if name:
            page_photos[name] = src.replace("d=low","d=high")

    # ── Team scores (div.text-lg.font-bold) ───────────────────────────────────
    score_blk = None
    for d in soup.find_all("div"):
        cls = " ".join(d.get("class",[]))
        if "text-lg" in cls and "font-bold" in cls:
            if re.search(r'\d+\s*/\s*\d+', d.get_text(strip=True)):
                score_blk = d; break

    if score_blk:
        rows = [c for c in score_blk.children if hasattr(c,'get_text')]
        for i, row in enumerate(rows[:2]):
            raw = row.get_text(" ", strip=True)
            m = re.match(r'([A-Z][A-Za-z\s&]{0,20}?)\s+(\d{1,4})\s*/\s*(\d{1,2})\s*\(\s*([\d.]+)\s*\)', raw)
            if m:
                key = "team1" if i == 0 else "team2"
                data[key]["name"]  = m.group(1).strip()
                data[key]["score"] = f"{m.group(2)}-{m.group(3)}"
                data[key]["overs"] = m.group(4)

    # ── Fallback: meta description ────────────────────────────────────────────
    meta = soup.find("meta", {"name":"description"})
    desc = re.sub(r'\s+', ' ', meta["content"] if meta else "")

    if not data["team1"]["name"]:
        dm = re.search(
            r'Follow\s+([A-Z][A-Za-z\s]{1,20}?)\s+(\d+/\d+)\s+\(([\d.]+)\)\s+vs\s+([A-Z][A-Za-z\s]{1,20}?)\s+(\d+/\d+)',
            desc)
        if dm:
            data["team1"].update({"name":dm.group(1).strip(),"score":dm.group(2).replace("/","-"),"overs":dm.group(3)})
            data["team2"].update({"name":dm.group(4).strip(),"score":dm.group(5).replace("/","-")})

    # ── Embedded Next.js miniscore JSON (most reliable source) ───────────────
    # Cricbuzz inlines live match data in self.__next_f.push scripts
    # Keys: currentRunRate, requiredRunRate, partnerShip, target, customStatus,
    #       lastWicket, batsmanStriker/NonStriker (id,name,runs,balls,fours,sixes,strikeRate)
    #       bowlerStriker/NonStriker (id,name,overs,maidens,economy,runs,wickets,playerUrl)
    bat_names = []   # collect for async photo fetch — defined here, used throughout
    mj = _extract_miniscore_json(html)
    if mj:
        if mj.get("crr"):      data["crr"]    = mj["crr"]
        if mj.get("rrr"):      data["rrr"]    = mj["rrr"]
        if mj.get("target"):   data["target"] = mj["target"]
        if mj.get("pship"):    data["partnership"] = mj["pship"]
        if mj.get("status"):   data["match_status"] = mj["status"][:50]
        if mj.get("lastWkt"):  data["last_wicket"] = mj["lastWkt"]
        # Batsmen — full stats from JSON (fours, sixes, SR)
        if mj.get("bat1"):
            b = mj["bat1"]
            photo = page_photos.get(b["name"],"") or _photo_cache.get(b["name"],"")
            data["batsman1"] = {**b, "photo": photo}
            bat_names.append(b["name"])
        if mj.get("bat2"):
            b = mj["bat2"]
            photo = page_photos.get(b["name"],"") or _photo_cache.get(b["name"],"")
            data["batsman2"] = {**b, "photo": photo}
            bat_names.append(b["name"])
        # Bowler — full stats from JSON
        if mj.get("bowl"):
            bw = mj["bowl"]
            photo = page_photos.get(bw["name"],"") or _photo_cache.get(bw["name"],"")
            data["bowler"] = {**bw, "photo": photo}
            bat_names.append(bw["name"])
        # Also store player slugs for photo lookup
        if mj.get("player_slugs"):
            for name, (pid, slug) in mj["player_slugs"].items():
                if name not in _photo_cache:
                    _player_slug_cache[name] = (pid, slug)

    # ── CRR / RRR / Target / Need — fallback from visible page text ──────────
    if not data["crr"]:
        mm = re.search(r'CRR[:\s]*([\d.]+)', full, re.I)
        if mm: data["crr"] = mm.group(1)
    if not data["rrr"]:
        mm = re.search(r'RRR[:\s]*([\d.]+)', full, re.I)
        if mm: data["rrr"] = mm.group(1)
    if not data["target"]:
        mm = re.search(r'[Tt]arget[:\s]*(\d+)', full)
        if mm: data["target"] = mm.group(1)
    if not data["need"]:
        mm = re.search(r'[Nn]eed[s]?\s+(\d+)\s*run', full)
        if mm: data["need"] = mm.group(1)

    # ── Live miniscore block (HTML) — over balls, fallback stats ─────────────
    mini = None
    for d in soup.find_all("div"):
        cls = " ".join(d.get("class",[]))
        if "p-2" in cls and "flex" in cls and "gap-4" in cls and "leading-normal" in cls:
            mini = d; break

    if mini:
        # Over number
        ov_el = mini.find("div", class_=lambda c: c and "text-2xl" in c and "font-bold" in c)
        if ov_el:
            try: data["current_over"] = int(ov_el.get_text(strip=True))
            except: pass

        inner = mini.find("div", class_=lambda c: c and "flex-col" in c and "w-full" in c)
        if inner:
            rows = [c for c in inner.children if hasattr(c,'get_text')]

            # Row 0: over balls + current score
            if rows:
                row0 = rows[0].get_text(" ", strip=True)
                balls_part = re.split(r'\s*\(\d+ runs?\)', row0)[0]
                ball_tokens = re.findall(r'\b(W|WD|NB|LB|[0-9])\b', balls_part, re.I)
                if ball_tokens:
                    data["last_over_balls"] = [b.upper() for b in ball_tokens]
                    data["current_ball"]    = data["last_over_balls"][-1]
                lw_m = re.search(r'([A-Z]{2,4})\s+(\d+)-(\d+)', row0)
                if lw_m:
                    data["last_wicket"] = f"{lw_m.group(1)} {lw_m.group(2)}/{lw_m.group(3)}"

            # Player row — batsmen + bowler
            player_row = inner.find("div", class_=lambda c: c and
                "justify-between" in c and "tb:justify-normal" in " ".join(c))
            if player_row:
                # Batsmen
                bat_blk = player_row.find("div", class_=lambda c: c and
                    "flex-col" in c and "gap-1" in c and
                    "wb:flex-row" not in " ".join(c))
                if bat_blk:
                    bat_rows = bat_blk.find_all("div", class_=lambda c: c and "gap-8" in c)
                    bats = []
                    for br in bat_rows:
                        divs = [d.get_text(strip=True) for d in br.find_all("div") if d.get_text(strip=True)]
                        if len(divs) >= 2:
                            name  = divs[0].replace("*","").strip()
                            score = divs[1]
                            rm    = re.match(r'(\d+)\((\d+)\)', score)
                            runs  = safe_int(rm.group(1)) if rm else 0
                            balls = safe_int(rm.group(2)) if rm else 0
                            sr    = f"{runs*100/balls:.2f}" if balls else "0.00"
                            photo = page_photos.get(name,"") or _photo_cache.get(name,"")
                            bats.append({"name":name,"runs":runs,"balls":balls,
                                         "fours":0,"sixes":0,"sr":sr,"photo":photo})
                            bat_names.append(name)
                    if len(bats) >= 1: data["batsman1"] = bats[0]
                    if len(bats) >= 2: data["batsman2"] = bats[1]
                    if len(bats) >= 2:
                        r = bats[0]["runs"]+bats[1]["runs"]
                        b = bats[0]["balls"]+bats[1]["balls"]
                        data["partnership"] = f"{r}({b})"

                # Bowler
                bowl_blk = player_row.find("div", class_=lambda c: c and "wb:flex-row" in " ".join(c))
                if bowl_blk:
                    divs = [d.get_text(strip=True) for d in bowl_blk.find_all("div") if d.get_text(strip=True)]
                    if len(divs) >= 2:
                        name = divs[0]
                        figs = divs[1]  # "4-0-42-2" = O-M-R-W
                        fm   = re.match(r'([\d.]+)-(\d+)-(\d+)-(\d+)', figs)
                        if fm:
                            overs   = fm.group(1)
                            maidens = safe_int(fm.group(2))
                            runs    = safe_int(fm.group(3))
                            wkts    = safe_int(fm.group(4))
                            try: eco = f"{runs/float(overs):.2f}"
                            except: eco = "0.00"
                            photo = page_photos.get(name,"") or _photo_cache.get(name,"")
                            data["bowler"] = {
                                "name":name,"overs":overs,"maidens":maidens,
                                "runs":runs,"wickets":wkts,"economy":eco,"photo":photo
                            }
                            bat_names.append(name)

    # ── Fallback batsmen from meta description ────────────────────────────────
    if not data.get("batsman1",{}).get("name") and desc:
        bat_ms = re.findall(r'([A-Z][a-zA-Z\s\.]{3,24}?)\s+(\d+)\((\d+)\)', desc)
        bats = []
        for bm in bat_ms[:2]:
            name  = bm[0].strip()
            runs  = safe_int(bm[1]); balls = safe_int(bm[2])
            sr    = f"{runs*100/balls:.2f}" if balls else "0.00"
            photo = page_photos.get(name,"") or _photo_cache.get(name,"")
            bats.append({"name":name,"runs":runs,"balls":balls,"fours":0,"sixes":0,"sr":sr,"photo":photo})
            bat_names.append(name)
        if bats and not data.get("batsman1",{}).get("name"):
            data["batsman1"] = bats[0]
        if len(bats)>1 and not data.get("batsman2",{}).get("name"):
            data["batsman2"] = bats[1]

    # ── Bowler fallback: [O-M-R-W] from commentary ───────────────────────────
    if not data.get("bowler",{}).get("name"):
        bm = re.search(r'([A-Z][a-zA-Z\s\.]{3,25}?)\s+\[([\d.]+)-(\d+)-(\d+)-(\d+)\]', full)
        if bm:
            overs = bm.group(2)
            try: eco = f"{safe_int(bm.group(4))/float(overs):.2f}"
            except: eco = "0.00"
            name  = bm.group(1).strip()
            photo = page_photos.get(name,"") or _photo_cache.get(name,"")
            data["bowler"] = {"name":name,"overs":overs,"maidens":safe_int(bm.group(3)),
                              "runs":safe_int(bm.group(4)),"wickets":safe_int(bm.group(5)),
                              "economy":eco,"photo":photo}
            bat_names.append(name)

    # ── Patch in photos for any player already in cache ───────────────────────
    for key in ["batsman1","batsman2","bowler"]:
        player = data.get(key,{})
        if player.get("name") and not player.get("photo"):
            cached = _photo_cache.get(player["name"],"")
            if cached: data[key]["photo"] = cached

    # ── Kick off background photo fetch for uncached players ─────────────────
    uncached = [n for n in set(bat_names) if n and n not in _photo_cache]
    if uncached:
        fetch_photos_async(uncached)

    return data

# ─── Main ─────────────────────────────────────────────────────────────────────
