# Deployment — Streamlit Community Cloud

How to keep the dashboard permanently available at a public URL, for free.

## Recommended host: Streamlit Community Cloud

**Streamlit Community Cloud** (share.streamlit.io) is the official free
hosting for Streamlit apps:

- Free, no credit card, unlimited public apps (one private app per account).
- Deploys directly from a GitHub repository and **redeploys automatically on
  every `git push`**.
- Roughly 690 MB – 2.7 GB RAM per app — ample for this dashboard
  (36k-row DuckDB + cached pandas frames).

Known limitations (honest expectations):

- The app **sleeps after ~12 hours without traffic** and wakes on the next
  visit (first page load takes ~30 s). Free hosting that never sleeps does
  not exist in 2026.
- Apps run in the United States; the Python version is fixed per app.
- Vercel is **not** suitable (static/serverless only — Streamlit is a
  long-running WebSocket server). Hugging Face Spaces no longer offers free
  Streamlit hosting. Render's free tier sleeps after 15 minutes.

## What is bundled in this repository

The repository is self-contained so the dashboard runs on the cloud **without
re-running the pipeline**:

| Bundled | Purpose |
|---|---|
| `data/processed/risk_portfolio.duckdb` (10.3 MB) | Curated warehouse — the dashboard reads only this |
| `reports/` (2.4 MB) | Generated PDFs + summaries for the Reporting page |
| `data/exports/` (4.5 MB) | Excel/CSV/Qlik artefacts for the Reporting page |

Excluded (regenerable): the synthetic landing zone
(`python -m synthetic_data.generate_data`, seed 42), pipeline logs, caches.
Total repository size: ~19 MB — far below GitHub's limits.

## Step-by-step deployment

### 1. Push the repository to GitHub

The local repository is already initialised and committed. Create an empty
repository on [github.com/new](https://github.com/new) (name it e.g.
`risk-portfolio-reporting`, Public), then from the project directory:

```powershell
git remote add origin https://github.com/<your-user>/risk-portfolio-reporting.git
git branch -M main
git push -u origin main
```

(Windows will ask for your GitHub credentials once; the Git Credential
Manager stores them.)

### 2. Deploy on Community Cloud

1. Go to [share.streamlit.io](https://share.streamlit.io) and sign in
   **with GitHub**.
2. Click **New app** → *Deploy an app*.
3. Select the repository `risk-portfolio-reporting`, branch `main`,
   main file path `app.py`.
4. Click **Deploy**. First build takes 2–4 minutes (pip installs
   `requirements.txt`).
5. Your app is live at `https://<something>.streamlit.app`.

### 3. Verify

Open the URL and walk the seven pages. The curated database is bundled, so
every page renders immediately — the pipeline does **not** need to run on
the host.

## Keeping it up to date

- **Code change:** commit + `git push` — Community Cloud redeploys within a
  minute.
- **New data snapshot:** re-run the pipeline locally, then commit the updated
  database:

```powershell
python -m synthetic_data.generate_data
python -m etl.pipeline --reset-db
python -m reporting.cli
git add data/processed/risk_portfolio.duckdb reports data/exports
git commit -m "Refresh curated data and reports"
git push
```

- **Restart/reboot:** from the app's ⋮ menu on share.streamlit.io.

## Behaviour on the cloud

- The dashboard is read-only towards the curated database. The Reporting
  page's *regenerate* button writes to the container's ephemeral filesystem —
  it works during a session but resets when the app restarts. That is
  expected and harmless for a demonstration.
- If the bundled database were ever missing, `app.py` shows instructions to
  run the pipeline instead of crashing.

## Alternatives (if requirements change)

| Host | When to choose it | Cost |
|---|---|---|
| Docker on any VPS / Fly.io / Railway | App must never sleep, or needs a custom domain | from ~$2–7/month |
| Render paid instance | Simple always-on hosting, no Docker knowledge | $7/month |
| Your own server | Full control, data privacy requirements | your hardware |

The repository deploys anywhere Docker runs: `streamlit run app.py
--server.port $PORT --server.address 0.0.0.0` inside a
`python:3.12-slim` image with `requirements.txt` installed.

## Data protection note

All bundled data is synthetic (fictional banks SSK001–SSK005, seed 42) and
labelled as such in every artefact. Publishing this repository publicly
involves no personal or confidential data. The GDPR-relevant step — replacing
the synthetic generator with real bank feeds — happens on-premises and is out
of scope by design.
