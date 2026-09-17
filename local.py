"""Run locally: .venv/bin/python local.py api|web (separate terminals)."""
import argparse
import json
import os
import secrets
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("service", choices=("api", "web"))
    args = parser.parse_args()
    os.umask(0o077)
    root = Path(__file__).resolve().parent
    os.chdir(root)
    config = Path.home() / ".config/tiktok-uploader/local.json"
    config.parent.mkdir(parents=True, exist_ok=True)
    if not config.exists():
        with config.open("x") as target:
            json.dump({"API_SECRET": secrets.token_urlsafe(32),
                       "FLASK_SECRET_KEY": secrets.token_urlsafe(32)}, target)
    os.environ.update(json.loads(config.read_text()))
    os.environ.update(API_BASE_URL="http://127.0.0.1:5050", SWAGGER="true", DEBUG="false")
    if args.service == "api":
        from api.server import app
    else:
        from web.app import app
    app.run(host="127.0.0.1", port=5050 if args.service == "api" else 5051,
            debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
