# TikTok Uploader

Automated TikTok video uploader via Selenium with multi-account support, web dashboard, and Swagger API.

## Quick start

### Local Docker — headless Chromium

The configured macOS deployment uses Colima, Docker and `docker-compose`.
API and dashboard run in separate containers; there is no VNC or X server.

```bash
colima start
cd ~/tools/TikTokUploader
docker-compose up -d --build
# Stop:
docker-compose down
```

Panel: http://127.0.0.1:5051; API: http://127.0.0.1:5050;
Swagger: http://127.0.0.1:5050/docs. Ports bind only to loopback.

Persistent data:
- `state/data.db`: migrated administrator, TikTok accounts/cookies and jobs.
- `uploads/` and `static/avatars/`: bind-mounted files.
- `~/.config/tiktok-uploader/docker.env`: private API and Flask session secrets,
  preserved from `~/.config/tiktok-uploader/local.json`.
- Root `data.db`: retained pre-migration database, not used by Docker.

Do not run the former `local.py` services alongside Docker. They use the old
database and the same host ports. Native services were stopped at cutover.
The secret files and state directory are not included in the image or Git.
`restart: unless-stopped` restarts containers when the Docker engine starts;
after restarting macOS, start Colima if it is not running.

Checks without publication:
```bash
.venv/bin/python check_local.py
docker-compose exec -T api python check_recovery.py
```

The recovery check closes and recreates a separate headless browser with a
temporary database. Production browser operations share one lock; a dead
session is recreated before the next operation, never by replaying an upload.
Actual publication is not verified by these checks. Upstream success
detection remains heuristic: do not automatically retry uncertain uploads.

## Ports

| Port (host) | Port (container) | Description |
|-------------|------------------|-------------|
| 5050 | 5000 | REST API + Swagger (`/docs`) |
| 5051 | 5001 | Web Dashboard |

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `HEADLESS` | `true` in Docker | Start Chromium without a visible window |
| `DEBUG` | `false` | Disable the dashboard's VNC view |
| `SWAGGER` | `false` | Enable Swagger UI at `/docs` on API port |
| `API_SECRET` | — | Bearer token for API authentication (generate: `openssl rand -hex 16`) |
| `CHROME_BINARY` | `/usr/bin/chromium` | Path to Chrome/Chromium binary |
| `CHROMEDRIVER_PATH` | `/usr/bin/chromedriver` | Path to chromedriver binary |
| `DB_PATH` | `/app/state/data.db` in Compose | Persistent SQLite database |
| `API_BASE_URL` | `http://api:5000` in Compose | Dashboard's internal API address |
| `FLASK_SECRET_KEY` | Private persisted value | Preserve dashboard login sessions |

## Authentication

### API Bearer Token

Set `API_SECRET` env to protect API endpoints:

```bash
# Generate a secret
openssl rand -hex 16
```

All API requests, including `/api/auth/*`, require `Authorization: Bearer <your-secret>`.
Swagger UI is accessible without a token. Dashboard API proxies require a
logged-in administrator; dashboard mutations require a same-origin request.

### Dashboard Admin

On first visit to the Web UI, you'll be prompted to create an admin account (username + password). After that, login is required to access the dashboard.

## Setup

1. Open the Web UI at `http://localhost:5051` → **Аккаунты**
2. Export your TikTok cookies via [CookieEditor](https://chromewebstore.google.com/detail/cookie-editor/hlkenndednhfkekhgcdicdfddnkalmdm)
3. Add account (name + cookies JSON) — cookies are verified automatically
4. Upload a video via the Web UI or API

## API

Swagger UI: `http://localhost:5050/docs` (when `SWAGGER=true`)

### Jobs

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/api/jobs` | Upload video (multipart: `video`, `account_id`, `description`, `tags`) |
| `GET` | `/api/jobs` | List all jobs |
| `GET` | `/api/jobs/<id>` | Get job status |

Job statuses: `IN_QUEUE` → `IN_PROGRESS` → `SUCCESS` / `FAIL`

### Accounts

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/accounts` | List all accounts |
| `POST` | `/api/accounts` | Add account (JSON: `name`, `cookies`) |
| `GET` | `/api/accounts/<id>` | Get account with cookies |
| `PUT` | `/api/accounts/<id>` | Update account |
| `DELETE` | `/api/accounts/<id>` | Delete account |

### Auth (no Bearer token required)

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/auth/setup` | Check if initial setup is needed |
| `POST` | `/api/auth/setup` | Create admin account (first time only) |
| `POST` | `/api/auth/login` | Login with admin credentials |

### Other

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/health` | Browser health check |
| `POST` | `/api/clipboard` | Set VNC clipboard text |

## License

ISC
