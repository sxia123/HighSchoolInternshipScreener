# High School Internship Screener

A full-stack **React.js + Python (FastAPI) + SQLite / Turso** web app that scans internship feeds on a **GitHub Actions cron** schedule and screens out college/PhD/adult-job noise—requiring **zero paid job API keys or LLM API keys**.

## Why this architecture?

- **Local SQLite (`sqlite3`) + Turso (`libSQL`)**: Runs with zero configuration locally on `backend/data/internships.db`. When `TURSO_DATABASE_URL` and `TURSO_AUTH_TOKEN` are set, it connects to Turso over its Hrana v2 HTTP pipeline API (`/v2/pipeline`) in pure Python—ideal for syncing an ephemeral GitHub Actions cron runner with a hosted FastAPI backend.
- **No paid API keys**:
  - **Public ATS JSON APIs**: Greenhouse, Lever, Ashby, and SmartRecruiters public career board endpoints.
  - **Remotive Public API**: Remote internships (with source attribution).
  - **LinkedIn without scraping / paid APIs**:
    1. **Google Alerts RSS feeds** targeting `site:linkedin.com/jobs` in your city (the UI includes a 1-click query generator).
    2. **LinkedIn Job Alert Email Importer**: Upload `.eml` files or paste raw LinkedIn alert emails (`jobs-noreply@linkedin.com`) directly in the UI or via CLI.
- **Rule-Based High School Screener**: Automatically filters out adult `"High school diploma required"` roles, `"Internal/International"` substring traps, and college/PhD-only internships, while surfacing an extracted eligibility evidence quote, compensation status, work mode, and distance in miles.

---

## Project Structure

- `backend/` — FastAPI server, SQLite/Turso adapter, rule screener, geocoder (built-in US metro seeds + cached Nominatim), source adapters, email parser, and `pytest` suite.
- `frontend/` — React + Vite web UI with area/radius search, filters, saved bookmarks, and Sources & LinkedIn Alerts modal.
- `.github/workflows/scan.yml` — Scheduled cron scanner (`0 1,13 * * *` UTC) and manual workflow trigger.

---

## Local Setup

### 1. Backend (Python)

```bash
cd backend
python -m venv .venv
# Windows PowerShell:
.\.venv\Scripts\Activate.ps1
# macOS/Linux:
# source .venv/bin/activate

pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Run a one-off CLI scan anytime:

```bash
cd backend
python scanner.py
```

Run tests:

```bash
cd backend
pytest -v
```

### 2. Frontend (React + Vite)

> Requires **Node.js 18+** and `npm`.

```bash
cd frontend
npm install
npm run dev
```

Open `http://localhost:5173`. Vite proxies `/api/*` requests to `http://127.0.0.1:8000`.

---

## Deploying with Turso + GitHub Actions Cron

1. Create a free **Turso** database (`turso db create hs-internships`) and token (`turso db tokens create hs-internships`).
2. In your GitHub repository **Settings → Secrets and variables → Actions**, add:
   - `TURSO_DATABASE_URL` (e.g. `libsql://hs-internships-yourname.turso.io`)
   - `TURSO_AUTH_TOKEN`
3. Deploy `backend/` to your Python host (Render, Fly.io, Railway, etc.) with those same two environment variables (plus `CORS_ORIGINS` set to your frontend URL and optional `SCAN_TRIGGER_SECRET`).
4. Deploy `frontend/` (`npm run build` → `frontend/dist`) to Vercel, Netlify, or Cloudflare Pages with `VITE_API_BASE_URL` pointing to your deployed backend URL.
5. GitHub Actions (`.github/workflows/scan.yml`) will automatically scan your configured sources twice daily and write verified matches into Turso.
