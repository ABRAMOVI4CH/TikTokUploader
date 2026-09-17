"""
TikTok Uploader Web Dashboard — port 5001.

Pages:
  /          — dashboard with health status and upload history
  /upload    — form to upload a new video
  /accounts  — manage TikTok accounts
"""

import logging
import os
import sys

import requests
from flask import Flask, Response, redirect, render_template, request, session, url_for

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("web.app")

app = Flask(__name__, template_folder="templates")
app.secret_key = os.environ.get("FLASK_SECRET_KEY", os.urandom(24).hex())

API_BASE = os.environ.get("API_BASE_URL", "http://127.0.0.1:5000")
DEBUG_MODE = os.environ.get("DEBUG", "false").lower() == "true"
API_SECRET = os.environ.get("API_SECRET", "")


@app.before_request
def protect_local_dashboard():
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        if request.headers.get("Origin") != request.host_url.rstrip("/"):
            return {"error": "Same-origin request required."}, 403
    if request.path.startswith("/api/") and not session.get("admin_user"):
        return {"error": "Login required."}, 401


@app.context_processor
def inject_globals():
    return {"debug_mode": DEBUG_MODE, "admin_user": session.get("admin_user")}


def _api(method: str, path: str, **kwargs):
    url = f"{API_BASE}{path}"
    try:
        headers = kwargs.pop("headers", {})
        if API_SECRET:
            headers["Authorization"] = f"Bearer {API_SECRET}"
        timeout = kwargs.pop("timeout", 30)
        resp = getattr(requests, method)(url, timeout=timeout, headers=headers, **kwargs)
        return resp.json(), resp.status_code
    except requests.exceptions.ConnectionError:
        return {"error": "API server is unreachable."}, 503
    except Exception as exc:
        logger.exception("API call failed: %s", exc)
        return {"error": str(exc)}, 500


def _proxy(method, path, **kwargs):
    url = f"{API_BASE}{path}"
    try:
        headers = kwargs.pop("headers", {})
        if API_SECRET:
            headers["Authorization"] = f"Bearer {API_SECRET}"
        timeout = kwargs.pop("timeout", 30)
        resp = getattr(requests, method)(url, timeout=timeout, headers=headers, **kwargs)
        return Response(resp.content, status=resp.status_code,
                        content_type=resp.headers.get("content-type"))
    except Exception as exc:
        return Response(f'{{"error":"{exc}"}}', status=502, content_type="application/json")


# ------------------------------------------------------------------
# Auth
# ------------------------------------------------------------------

def login_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("admin_user"):
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return decorated


@app.route("/setup", methods=["GET", "POST"])
def setup():
    check, _ = _api("get", "/api/auth/setup")
    if not check.get("setup_required"):
        return redirect(url_for("login"))
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        if not username or not password:
            return render_template("setup.html", error="Заполните все поля.")
        if len(password) < 4:
            return render_template("setup.html", error="Пароль минимум 4 символа.")
        result, status = _api("post", "/api/auth/setup", json={"username": username, "password": password})
        if status == 201:
            session["admin_user"] = username
            return redirect(url_for("dashboard"))
        return render_template("setup.html", error=result.get("error", "Ошибка."))
    return render_template("setup.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    check, _ = _api("get", "/api/auth/setup")
    if check.get("setup_required"):
        return redirect(url_for("setup"))
    if session.get("admin_user"):
        return redirect(url_for("dashboard"))
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "").strip()
        result, status = _api("post", "/api/auth/login", json={"username": username, "password": password})
        if status == 200:
            session["admin_user"] = username
            return redirect(url_for("dashboard"))
        return render_template("login.html", error="Неверный логин или пароль.")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


# ------------------------------------------------------------------
# Pages
# ------------------------------------------------------------------

@app.route("/")
@login_required
def dashboard():
    health_data, _ = _api("get", "/api/health")
    tasks_data, _ = _api("get", "/api/tasks")
    tasks = tasks_data if isinstance(tasks_data, list) else []
    return render_template("dashboard.html", health=health_data, tasks=tasks)


@app.route("/upload")
@login_required
def upload():
    accounts_data, _ = _api("get", "/api/accounts")
    accounts = accounts_data if isinstance(accounts_data, list) else []
    return render_template("upload.html", accounts=accounts)


@app.route("/vnc")
@login_required
def vnc():
    if not DEBUG_MODE:
        return redirect(url_for("dashboard"))
    return render_template("vnc.html")


@app.route("/accounts")
@login_required
def accounts():
    accounts_data, _ = _api("get", "/api/accounts")
    accounts_list = accounts_data if isinstance(accounts_data, list) else []
    return render_template("accounts.html", accounts=accounts_list)


# ------------------------------------------------------------------
# API proxies
# ------------------------------------------------------------------

@app.route("/api/upload", methods=["POST"])
def proxy_upload():
    files = {}
    for key, f in request.files.items():
        files[key] = (f.filename, f.stream, f.content_type)
    data = {k: v for k, v in request.form.items()}
    return _proxy("post", "/api/upload", data=data, files=files)


@app.route("/api/accounts", methods=["GET"])
def proxy_list_accounts():
    return _proxy("get", "/api/accounts")


@app.route("/api/accounts", methods=["POST"])
def proxy_add_account():
    return _proxy("post", "/api/accounts", json=request.get_json(force=True), timeout=120)


@app.route("/api/accounts/<int:account_id>", methods=["GET"])
def proxy_get_account(account_id):
    return _proxy("get", f"/api/accounts/{account_id}")


@app.route("/api/accounts/<int:account_id>", methods=["PUT"])
def proxy_update_account(account_id):
    return _proxy("put", f"/api/accounts/{account_id}", json=request.get_json(force=True), timeout=120)


@app.route("/api/accounts/<int:account_id>", methods=["DELETE"])
def proxy_delete_account(account_id):
    return _proxy("delete", f"/api/accounts/{account_id}")


@app.route("/api/clipboard", methods=["POST"])
def proxy_clipboard():
    return _proxy("post", "/api/clipboard", json=request.get_json(force=True))


@app.route("/static/avatars/<path:filename>")
def proxy_avatar(filename):
    return _proxy("get", f"/static/avatars/{filename}")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5001, debug=False)
