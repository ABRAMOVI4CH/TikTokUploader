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
| `CHROME_BINARY` | `/usr/bin/chromium` | Path to Chrome/Chromium binary |
| `CHROMEDRIVER_PATH` | `/usr/bin/chromedriver` | Path to chromedriver binary |

## Setup

1. Open the Web UI at `http://localhost:5051` → **Аккаунты**
2. Export your TikTok cookies via [EditThisCookie](https://chrome.google.com/webstore/detail/editthiscookie/fngmhnnpilhplaeedifhccceomclgfbg)
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

### Other

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/api/health` | Browser health check |
| `POST` | `/api/clipboard` | Set VNC clipboard text |

## License

ISC
