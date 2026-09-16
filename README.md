# TikTok Uploader

Automated TikTok video uploader via Selenium with multi-account support, web dashboard, and Swagger API.

## Quick start

### Docker Compose (from GHCR)

```yaml
# docker-compose.yml
services:
  tiktok-uploader:
    image: ghcr.io/abramovi4ch/tiktokuploader:latest
    container_name: tiktok-uploader
    ports:
      - "5050:5000"  # API + Swagger
      - "5051:5001"  # Web UI
      - "5901:5900"  # VNC
    volumes:
      - ./uploads:/app/uploads
    restart: unless-stopped
    shm_size: "512m"
    environment:
      - PYTHONUNBUFFERED=1
      - VNC_PASSWORD=1111
      - DEBUG=true
      - DASHBOARD=true
      - SWAGGER=true
      - API_SECRET=          # openssl rand -hex 16
```

```bash
docker pull ghcr.io/abramovi4ch/tiktokuploader:latest
docker compose up -d
```

### Build from source

```bash
git clone https://github.com/ABRAMOVI4CH/TikTokUploader.git
cd TikTokUploader
docker compose up --build -d
```

## Ports

| Port (host) | Port (container) | Description |
|-------------|------------------|-------------|
| 5050 | 5000 | REST API + Swagger (`/docs`) |
| 5051 | 5001 | Web Dashboard |
| 5901 | 5900 | VNC (browser view) |

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DEBUG` | `false` | Enable VNC server for browser debugging |
| `DASHBOARD` | `true` | Enable web dashboard on port 5001 |
| `SWAGGER` | `false` | Enable Swagger UI at `/docs` on API port |
| `VNC_PASSWORD` | — | VNC connection password |
| `API_SECRET` | — | Bearer token for API authentication (generate: `openssl rand -hex 16`) |
| `CHROME_BINARY` | `/usr/bin/chromium` | Path to Chrome/Chromium binary |
| `CHROMEDRIVER_PATH` | `/usr/bin/chromedriver` | Path to chromedriver binary |

## Authentication

### API Bearer Token

Set `API_SECRET` env to protect API endpoints:

```bash
# Generate a secret
openssl rand -hex 16
```

All API requests must include `Authorization: Bearer <your-secret>`. Auth endpoints (`/api/auth/*`) and Swagger UI are accessible without a token.

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
