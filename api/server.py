"""
TikTok Uploader API Server — port 5000.

Endpoints:
  GET  /api/health             — browser health
  GET  /api/accounts           — list accounts
  POST /api/accounts           — add account (validates cookies)
  GET  /api/accounts/<id>      — get account
  DELETE /api/accounts/<id>    — delete account
  POST /api/upload             — upload video (multipart + account_id)
  GET  /api/tasks              — list tasks
  GET  /api/status/<id>        — task status
  POST /api/clipboard          — set clipboard text
"""

import json
import logging
import os
import sys
import threading
import uuid

from flask import Flask, jsonify, request, send_from_directory

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db import get_db, init_db, add_account, get_account, list_accounts, update_account, delete_account
from db import add_task, update_task, get_task, list_tasks
from uploader.tiktok_uploader import TikTokUploader

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("api.server")

app = Flask(__name__)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UPLOADS_DIR = os.path.join(BASE_DIR, "uploads")
AVATARS_DIR = os.path.join(BASE_DIR, "static", "avatars")
os.makedirs(UPLOADS_DIR, exist_ok=True)
os.makedirs(AVATARS_DIR, exist_ok=True)

init_db()

# ------------------------------------------------------------------
# Uploader singleton
# ------------------------------------------------------------------
_uploader: TikTokUploader | None = None
_uploader_lock = threading.Lock()


def get_uploader() -> TikTokUploader:
    global _uploader
    with _uploader_lock:
        if _uploader is None:
            logger.info("Creating TikTokUploader instance…")
            _uploader = TikTokUploader()
        return _uploader


# ------------------------------------------------------------------
# Health
# ------------------------------------------------------------------

@app.route("/api/health")
def health():
    try:
        uploader = get_uploader()
        status = uploader.check_status()
    except Exception as exc:
        status = {"alive": False, "error": str(exc)}
    return jsonify(status)


# ------------------------------------------------------------------
# Accounts
# ------------------------------------------------------------------

@app.route("/api/accounts")
def api_list_accounts():
    accounts = list_accounts()
    # Don't send cookies in list response
    for a in accounts:
        a.pop("cookies", None)
    return jsonify(accounts)


@app.route("/api/accounts/<int:account_id>")
def api_get_account(account_id: int):
    account = get_account(account_id)
    if not account:
        return jsonify({"error": "Account not found."}), 404
    return jsonify(account)


@app.route("/api/accounts", methods=["POST"])
def api_add_account():
    """Add account: validate cookies, scrape profile, save."""
    data = request.get_json(force=True)
    name = data.get("name", "").strip()
    cookies = data.get("cookies")

    if not name:
        return jsonify({"error": "Name is required."}), 400
    if not cookies or not isinstance(cookies, list):
        return jsonify({"error": "Cookies must be a JSON array."}), 400

    try:
        uploader = get_uploader()
        result = uploader.verify_account(cookies)
    except Exception as exc:
        logger.exception("Account verification error: %s", exc)
        return jsonify({"error": f"Verification failed: {exc}"}), 500

    if not result["valid"]:
        return jsonify({"error": "Cookies are invalid or expired. Login not detected."}), 400

    # Save avatar
    avatar_path = ""
    if result["avatar_url"]:
        avatar_filename = f"{uuid.uuid4().hex[:12]}.jpg"
        full_path = os.path.join(AVATARS_DIR, avatar_filename)
        if uploader.download_avatar(result["avatar_url"], full_path):
            avatar_path = avatar_filename

    account_id = add_account(
        name=name,
        cookies=cookies,
        tiktok_username=result["username"],
        tiktok_nickname=result["nickname"],
        avatar_path=avatar_path,
    )

    return jsonify({
        "success": True,
        "account_id": account_id,
        "username": result["username"],
        "nickname": result["nickname"],
    }), 201


@app.route("/api/accounts/<int:account_id>", methods=["PUT"])
def api_update_account(account_id: int):
    """Update account cookies and re-verify."""
    account = get_account(account_id)
    if not account:
        return jsonify({"error": "Account not found."}), 404

    data = request.get_json(force=True)
    cookies = data.get("cookies")
    name = data.get("name")

    updates = {}
    if name:
        updates["name"] = name.strip()

    if cookies and isinstance(cookies, list):
        try:
            uploader = get_uploader()
            result = uploader.verify_account(cookies)
        except Exception as exc:
            return jsonify({"error": f"Verification failed: {exc}"}), 500

        if not result["valid"]:
            return jsonify({"error": "New cookies are invalid or expired."}), 400

        updates["cookies"] = cookies
        if result["username"]:
            updates["tiktok_username"] = result["username"]
        if result["nickname"]:
            updates["tiktok_nickname"] = result["nickname"]
        if result["avatar_url"]:
            avatar_filename = f"{uuid.uuid4().hex[:12]}.jpg"
            full_path = os.path.join(AVATARS_DIR, avatar_filename)
            if uploader.download_avatar(result["avatar_url"], full_path):
                # Remove old avatar
                if account["avatar_path"]:
                    old = os.path.join(AVATARS_DIR, account["avatar_path"])
                    if os.path.exists(old):
                        os.remove(old)
                updates["avatar_path"] = avatar_filename

    if updates:
        update_account(account_id, **updates)

    return jsonify({"success": True})


@app.route("/api/accounts/<int:account_id>", methods=["DELETE"])
def api_delete_account(account_id: int):
    account = get_account(account_id)
    if not account:
        return jsonify({"error": "Account not found."}), 404
    # Remove avatar file
    if account["avatar_path"]:
        p = os.path.join(AVATARS_DIR, account["avatar_path"])
        if os.path.exists(p):
            os.remove(p)
    delete_account(account_id)
    return jsonify({"success": True})


# ------------------------------------------------------------------
# Avatars static
# ------------------------------------------------------------------

@app.route("/static/avatars/<path:filename>")
def serve_avatar(filename):
    return send_from_directory(AVATARS_DIR, filename)


# ------------------------------------------------------------------
# Upload
# ------------------------------------------------------------------

def _do_upload(task_id: str, video_path: str, description: str,
               tags: list[str], cookies: list):
    update_task(task_id, status="uploading", message="Upload in progress…")
    try:
        uploader = get_uploader()
        result = uploader.upload_video(video_path, description, cookies, tags)
        update_task(task_id, status=result["status"], message=result["message"])
    except Exception as exc:
        logger.exception("Upload worker error: %s", exc)
        update_task(task_id, status="failed", message=f"Worker exception: {exc}")


@app.route("/api/upload", methods=["POST"])
def upload():
    if "video" not in request.files:
        return jsonify({"error": "No video file in request (field: 'video')."}), 400

    video_file = request.files["video"]
    if video_file.filename == "":
        return jsonify({"error": "Empty filename."}), 400

    account_id = request.form.get("account_id")
    if not account_id:
        return jsonify({"error": "Account not selected."}), 400

    account = get_account(int(account_id))
    if not account:
        return jsonify({"error": "Account not found."}), 404

    description = request.form.get("description", "")
    tags_raw = request.form.get("tags", "")
    tags = [t.strip().lstrip("#") for t in tags_raw.split(",") if t.strip()] if tags_raw else []

    ext = os.path.splitext(video_file.filename)[1] or ".mp4"
    saved_name = f"{uuid.uuid4()}{ext}"
    saved_path = os.path.join(UPLOADS_DIR, saved_name)

    try:
        video_file.save(saved_path)
    except Exception as exc:
        return jsonify({"error": f"Could not save file: {exc}"}), 500

    task_id = str(uuid.uuid4())
    add_task(task_id, int(account_id), video_file.filename, description, tags_raw)

    t = threading.Thread(
        target=_do_upload,
        args=(task_id, saved_path, description, tags, account["cookies"]),
        daemon=True,
    )
    t.start()

    return jsonify({"task_id": task_id, "message": "Upload queued."}), 202


# ------------------------------------------------------------------
# Tasks
# ------------------------------------------------------------------

@app.route("/api/status/<task_id>")
def status(task_id: str):
    task = get_task(task_id)
    if task is None:
        return jsonify({"error": "Task not found."}), 404
    return jsonify(task)


@app.route("/api/tasks")
def api_list_tasks():
    return jsonify(list_tasks())


# ------------------------------------------------------------------
# Clipboard
# ------------------------------------------------------------------

@app.route("/api/clipboard", methods=["POST"])
def set_clipboard():
    data = request.get_json(force=True)
    text = data.get("text", "")
    if not text:
        return jsonify({"error": "No text provided."}), 400
    try:
        uploader = get_uploader()
        uploader.driver.execute_cdp_cmd("Browser.grantPermissions", {
            "permissions": ["clipboardReadWrite", "clipboardSanitizedWrite"],
            "origin": uploader.driver.current_url
        })
        uploader.driver.execute_script("navigator.clipboard.writeText(arguments[0]);", text)
        return jsonify({"success": True, "message": f"Copied {len(text)} chars to clipboard."})
    except Exception as exc:
        import subprocess
        try:
            proc = subprocess.run(["xclip", "-selection", "clipboard"],
                                  input=text.encode(), timeout=5)
            if proc.returncode == 0:
                return jsonify({"success": True, "message": f"Copied {len(text)} chars via xclip."})
        except Exception:
            pass
        return jsonify({"error": str(exc)}), 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
