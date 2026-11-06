# System Monitor

Real-time CPU, memory, disk and network monitoring dashboard with history, email alerts and a settings page.

![Dashboard](docs/dashboard.png)

## Features
- Live cards: CPU, memory, disk, network upload/download, uptime
- Live charts: CPU and memory history, per-core CPU bars, network traffic
- **History in SQLite** with time-range filter (5 min, 1 hour, 6 hours, 24 hours, 7 days)
- **Email alerts** when CPU or memory crosses a threshold (with a cooldown to avoid spam)
- **Settings page**: change thresholds, cooldown and alert email from the UI
- Top 5 processes and recent alert history
- Docker support

## Tech stack
Python, FastAPI, psutil, SQLite, Chart.js, Docker

## How it works
A background thread reads the system every 2 seconds with `psutil` and stores each reading in SQLite.
The browser calls the REST API every 3 seconds to draw the charts. For long ranges (24 hours, 7 days) the API
averages readings into about 300 points so charts stay fast. Alerts are checked on every reading.

```
psutil -> collector thread -> SQLite -> FastAPI REST API -> Chart.js dashboard
                 |
                 +-> threshold check -> email (SMTP) + alert log
```

## Run locally
```bash
pip install -r requirements.txt
uvicorn app:app --reload
```
Open http://localhost:8000

`chart.js` (the Chart.js library file) must stay in the same folder as `app.py`.
Download it from https://cdn.jsdelivr.net/npm/chart.js@4.4.1/dist/chart.umd.min.js and save it as `chart.js`.

## Run with Docker
```bash
docker compose up --build
```
Open http://localhost:8000. Data is stored in a Docker volume.
Note: inside Docker the dashboard shows the resources visible to the container, so numbers may reflect the Docker VM and not your laptop.

## Email alerts setup
Use a Gmail **App Password** (Google Account -> Security -> 2-Step Verification -> App passwords).

PowerShell:
```powershell
$env:SMTP_USER="you@gmail.com"
$env:SMTP_PASS="your-app-password"
py -m uvicorn app:app --reload
```
Then open Settings in the dashboard, enable email alerts, enter the recipient and click **Send test email**.

Docker: set the same variables before `docker compose up` (or in a `.env` file, which is git-ignored).

## API
| Endpoint | Description |
|---|---|
| `GET /api/stats` | Latest reading |
| `GET /api/history?minutes=60` | Averaged history |
| `GET /api/processes` | Top 5 processes by memory |
| `GET /api/alerts` | Last 10 alerts |
| `GET/POST /api/settings` | Read / update thresholds and email settings |
| `POST /api/test-email` | Send a test email |

## Screenshots
Add screenshots in the `docs/` folder: `dashboard.png`, `settings.png`.

## Next steps
Login (JWT), monitor multiple machines with agents, Prometheus + Grafana export, anomaly detection.
