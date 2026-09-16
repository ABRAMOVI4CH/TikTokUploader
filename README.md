# TikTok Uploader

Automated TikTok video uploader via Selenium. Runs in Docker with VNC access to the browser.

## Architecture

| Component | Port | Description |
|-----------|------|-------------|
| API server | 5000 | REST API for uploads, tasks, cookies |
| Web UI | 5001 | Dashboard, upload form, cookie editor |
| VNC | 5900 | Live view of the Chromium browser |

## Quick start

```bash
docker compose up --build -d
```

**Ports on host:**
- `http://localhost:5051` — Web UI
- `http://localhost:5050` — API
- `localhost:5901` — VNC (password: `1111`)

## Setup

1. Open the Web UI → **Управление куками**
2. Export your TikTok cookies using [EditThisCookie](https://chrome.google.com/webstore/detail/editthiscookie/fngmhnnpilhplaeedifhccceomclgfbg) browser extension
3. Paste the JSON into the cookie editor and save
4. Upload a video via the Web UI or API

Cookies are injected automatically before each upload — no separate login step needed.

## API

### Upload video
```
POST /api/upload
Content-Type: multipart/form-data

Fields: video (file), description (string), tags (comma-separated string)
```

### Check task status
```
GET /api/status/<task_id>
```

### List all tasks
```
GET /api/tasks
```

### Health check
```
GET /api/health
```

### Cookies
```
GET /api/cookies        — read cookies.json
PUT /api/cookies        — overwrite cookies.json (JSON array body)
```

## Environment variables

| Variable | Default | Description |
|----------|---------|-------------|
| `VNC_PASSWORD` | `1111` | VNC connection password |
| `CHROME_BINARY` | `/usr/bin/chromium` | Path to Chrome/Chromium |
| `CHROMEDRIVER_PATH` | `/usr/bin/chromedriver` | Path to chromedriver |

## License

ISC
