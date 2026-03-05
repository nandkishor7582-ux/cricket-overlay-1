# 🏏 Live Cricket OBS Overlay — Cloud Version

No Python on your PC needed. Deploy once → open a URL → done.

---

## ⚡ Quick Deploy to Railway (FREE, takes 5 minutes)

### Step 1 — Upload to GitHub
1. Go to **github.com** → Sign in (or create free account)
2. Click **"New repository"** → name it `cricket-overlay` → click **Create**
3. Upload all these files (drag & drop onto the page):
   - `app.py`
   - `scraper_core.py`
   - `livematch.html`
   - `requirements.txt`
   - `Procfile`
   - `runtime.txt`
   - `railway.json`

### Step 2 — Deploy on Railway
1. Go to **railway.app** → Sign in with GitHub
2. Click **"New Project"** → **"Deploy from GitHub repo"**
3. Select your `cricket-overlay` repo
4. Railway auto-detects everything and deploys in ~2 minutes
5. Click **"Generate Domain"** → you get a URL like:
   `https://cricket-overlay-production.up.railway.app`

### Step 3 — Use it
Open your URL in a browser — you'll see a page to enter a match ID.

**Getting the Match ID:**
- Go to `cricbuzz.com` → find your live match
- Copy the number from the URL:
  `cricbuzz.com/live-cricket-scores/`**`12345`**`/india-vs-england`
- Enter that number on the landing page

**Your overlay URL will be:**
```
https://your-app.railway.app/overlay?match=12345
```

---

## 📺 Adding to OBS

1. In OBS → **Sources** → click **+** → **Browser**
2. Set URL: `https://your-app.railway.app/overlay?match=12345`
3. Set Width: **1280**, Height: **720**
4. ✅ Enable: **"Shutdown source when not visible"**
5. Click OK

The overlay updates live every 3 seconds automatically.

---

## 🔄 Changing Match During a Session

Just change the match number in the URL:
- `...overlay?match=12345` → `...overlay?match=67890`

Each match ID runs its own background scraper automatically.

---

## 🆓 Free Tier Limits

**Railway free tier:**
- 500 hours/month (enough for ~16 hours/day)
- App sleeps after 10 minutes of no requests (wakes up in ~5s)
- To keep it always awake: upgrade to Hobby ($5/month) or use Render.com free tier

**Render.com alternative (also free):**
1. Go to render.com → New → Web Service
2. Connect GitHub repo
3. Set Build Command: `pip install -r requirements.txt`
4. Set Start Command: `gunicorn app:app --bind 0.0.0.0:$PORT --workers 1 --threads 8`
5. Deploy → get your URL

---

## 📁 Files

| File | Purpose |
|------|---------|
| `app.py` | Flask web server — handles URLs, serves overlay |
| `scraper_core.py` | Cricbuzz scraper + parser logic |
| `livematch.html` | The OBS overlay (1280×720) |
| `requirements.txt` | Python dependencies |
| `Procfile` | Tells Railway/Render how to start the app |

---

## 🛠 Local Testing (optional)

```bash
pip install flask requests beautifulsoup4
python app.py
# Open: http://localhost:8000
```
