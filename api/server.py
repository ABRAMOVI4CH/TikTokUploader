"""
TikTok Uploader API Server — port 5000.
Swagger UI available at /docs when SWAGGER=true.
"""

import json
import logging
import os
import sys
import threading
import uuid

from flask import Flask, send_from_directory
from flask_restx import Api, Resource, fields, reqparse
from werkzeug.datastructures import FileStorage

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db import (
    init_db, add_account, get_account, list_accounts,
    update_account, delete_account, add_task, update_task,
    get_task, list_tasks,
)
from uploader.tiktok_uploader import TikTokUploader

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("api.server")

app = Flask(__name__)

SWAGGER_ENABLED = os.environ.get("SWAGGER", "false").lower() == "true"

api = Api(
    app,
    version="1.0",
    title="TikTok Uploader API",
    description="API for managing TikTok accounts and uploading videos",
    doc="/docs" if SWAGGER_ENABLED else False,
)

# Namespaces
ns_health = api.namespace("health", path="/api/health", description="Health check")
ns_accounts = api.namespace("accounts", path="/api/accounts", description="TikTok account management")
ns_jobs = api.namespace("jobs", path="/api/jobs", description="Upload jobs")
ns_clipboard = api.namespace("clipboard", path="/api/clipboard", description="VNC clipboard")

# ------------------------------------------------------------------
# Paths
# ------------------------------------------------------------------
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
UPLOADS_DIR = os.path.join(BASE_DIR, "uploads")
AVATARS_DIR = os.path.join(BASE_DIR, "static", "avatars")
os.makedirs(UPLOADS_DIR, exist_ok=True)
os.makedirs(AVATARS_DIR, exist_ok=True)

init_db()

# ------------------------------------------------------------------
# Job statuses
# ------------------------------------------------------------------
class Status:
    IN_QUEUE = "IN_QUEUE"
    IN_PROGRESS = "IN_PROGRESS"
    SUCCESS = "SUCCESS"
    FAIL = "FAIL"

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
# Models
# ------------------------------------------------------------------

account_input = api.model("AccountInput", {
    "name": fields.String(required=True, description="Display name for the account"),
    "cookies": fields.List(fields.Raw, required=True, description="TikTok cookies as JSON array"),
})

account_update = api.model("AccountUpdate", {
    "name": fields.String(description="New display name"),
    "cookies": fields.List(fields.Raw, description="New cookies (will be re-verified)"),
})

account_output = api.model("Account", {
    "id": fields.Integer,
    "name": fields.String,
    "tiktok_username": fields.String,
    "tiktok_nickname": fields.String,
    "avatar_path": fields.String,
    "created_at": fields.String,
})

account_detail = api.inherit("AccountDetail", account_output, {
    "cookies": fields.List(fields.Raw),
})

job_output = api.model("Job", {
    "id": fields.String(description="Job UUID"),
    "account_id": fields.Integer,
    "account_name": fields.String,
    "status": fields.String(enum=["IN_QUEUE", "IN_PROGRESS", "SUCCESS", "FAIL"]),
    "filename": fields.String,
    "description": fields.String,
    "tags": fields.String,
    "message": fields.String,
    "created_at": fields.String,
    "updated_at": fields.String,
})

error_model = api.model("Error", {
    "error": fields.String,
})

# ------------------------------------------------------------------
# Health
# ------------------------------------------------------------------

@ns_health.route("")
class HealthCheck(Resource):
    @ns_health.doc("health_check")
    def get(self):
        """Check browser health status"""
        try:
            uploader = get_uploader()
            return uploader.check_status()
        except Exception as exc:
            return {"alive": False, "error": str(exc)}


# ------------------------------------------------------------------
# Accounts
# ------------------------------------------------------------------

@ns_accounts.route("")
class AccountList(Resource):
    @ns_accounts.doc("list_accounts")
    @ns_accounts.marshal_list_with(account_output)
    def get(self):
        """List all accounts (without cookies)"""
        accounts = list_accounts()
        for a in accounts:
            a.pop("cookies", None)
        return accounts

    @ns_accounts.doc("add_account")
    @ns_accounts.expect(account_input)
    @ns_accounts.response(201, "Account created")
    @ns_accounts.response(400, "Validation error", error_model)
    def post(self):
        """Add a new account — cookies are verified before saving"""
        data = api.payload
        name = (data.get("name") or "").strip()
        cookies = data.get("cookies")

        if not name:
            return {"error": "Name is required."}, 400
        if not cookies or not isinstance(cookies, list):
            return {"error": "Cookies must be a JSON array."}, 400

        try:
            uploader = get_uploader()
            result = uploader.verify_account(cookies)
        except Exception as exc:
            logger.exception("Account verification error: %s", exc)
            return {"error": f"Verification failed: {exc}"}, 500

        if not result["valid"]:
            return {"error": "Cookies are invalid or expired."}, 400

        avatar_path = ""
        if result["avatar_url"]:
            avatar_filename = f"{uuid.uuid4().hex[:12]}.jpg"
            full_path = os.path.join(AVATARS_DIR, avatar_filename)
            if uploader.download_avatar(result["avatar_url"], full_path):
                avatar_path = avatar_filename

        account_id = add_account(
            name=name, cookies=cookies,
            tiktok_username=result["username"],
            tiktok_nickname=result["nickname"],
            avatar_path=avatar_path,
        )

        return {
            "success": True,
            "account_id": account_id,
            "username": result["username"],
            "nickname": result["nickname"],
        }, 201


@ns_accounts.route("/<int:account_id>")
@ns_accounts.param("account_id", "Account ID")
class AccountDetail(Resource):
    @ns_accounts.doc("get_account")
    @ns_accounts.marshal_with(account_detail)
    @ns_accounts.response(404, "Not found", error_model)
    def get(self, account_id):
        """Get account details including cookies"""
        account = get_account(account_id)
        if not account:
            api.abort(404, "Account not found.")
        return account

    @ns_accounts.doc("update_account")
    @ns_accounts.expect(account_update)
    @ns_accounts.response(404, "Not found", error_model)
    def put(self, account_id):
        """Update account name and/or cookies (re-verified)"""
        account = get_account(account_id)
        if not account:
            return {"error": "Account not found."}, 404

        data = api.payload
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
                return {"error": f"Verification failed: {exc}"}, 500

            if not result["valid"]:
                return {"error": "New cookies are invalid or expired."}, 400

            updates["cookies"] = cookies
            if result["username"]:
                updates["tiktok_username"] = result["username"]
            if result["nickname"]:
                updates["tiktok_nickname"] = result["nickname"]
            if result["avatar_url"]:
                avatar_filename = f"{uuid.uuid4().hex[:12]}.jpg"
                full_path = os.path.join(AVATARS_DIR, avatar_filename)
                if uploader.download_avatar(result["avatar_url"], full_path):
                    if account["avatar_path"]:
                        old = os.path.join(AVATARS_DIR, account["avatar_path"])
                        if os.path.exists(old):
                            os.remove(old)
                    updates["avatar_path"] = avatar_filename

        if updates:
            update_account(account_id, **updates)

        return {"success": True}

    @ns_accounts.doc("delete_account")
    @ns_accounts.response(404, "Not found", error_model)
    def delete(self, account_id):
        """Delete an account"""
        account = get_account(account_id)
        if not account:
            return {"error": "Account not found."}, 404
        if account["avatar_path"]:
            p = os.path.join(AVATARS_DIR, account["avatar_path"])
            if os.path.exists(p):
                os.remove(p)
        delete_account(account_id)
        return {"success": True}


# ------------------------------------------------------------------
# Avatars
# ------------------------------------------------------------------

@app.route("/static/avatars/<path:filename>")
def serve_avatar(filename):
    return send_from_directory(AVATARS_DIR, filename)


# ------------------------------------------------------------------
# Jobs (upload)
# ------------------------------------------------------------------

upload_parser = reqparse.RequestParser()
upload_parser.add_argument("video", location="files", type=FileStorage, required=True, help="Video file")
upload_parser.add_argument("account_id", location="form", type=int, required=True, help="Account ID")
upload_parser.add_argument("description", location="form", type=str, default="", help="Video caption")
upload_parser.add_argument("tags", location="form", type=str, default="", help="Comma-separated tags")


def _do_upload(task_id: str, video_path: str, description: str,
               tags: list[str], cookies: list):
    update_task(task_id, status=Status.IN_PROGRESS, message="Upload in progress…")
    try:
        uploader = get_uploader()
        result = uploader.upload_video(video_path, description, cookies, tags)
        final_status = Status.SUCCESS if result["status"] == "success" else Status.FAIL
        update_task(task_id, status=final_status, message=result["message"])
    except Exception as exc:
        logger.exception("Upload worker error: %s", exc)
        update_task(task_id, status=Status.FAIL, message=f"Worker exception: {exc}")


@ns_jobs.route("")
class JobList(Resource):
    @ns_jobs.doc("list_jobs")
    @ns_jobs.marshal_list_with(job_output)
    def get(self):
        """List all upload jobs, newest first"""
        return list_tasks()

    @ns_jobs.doc("create_job")
    @ns_jobs.expect(upload_parser)
    @ns_jobs.response(202, "Job created")
    @ns_jobs.response(400, "Validation error", error_model)
    @ns_jobs.response(404, "Account not found", error_model)
    def post(self):
        """Upload a video — creates a background job"""
        args = upload_parser.parse_args()
        video_file = args["video"]
        account_id = args["account_id"]
        description = args["description"] or ""
        tags_raw = args["tags"] or ""

        if not video_file or video_file.filename == "":
            return {"error": "No video file."}, 400

        account = get_account(account_id)
        if not account:
            return {"error": "Account not found."}, 404

        tags = [t.strip().lstrip("#") for t in tags_raw.split(",") if t.strip()] if tags_raw else []

        ext = os.path.splitext(video_file.filename)[1] or ".mp4"
        saved_name = f"{uuid.uuid4()}{ext}"
        saved_path = os.path.join(UPLOADS_DIR, saved_name)

        try:
            video_file.save(saved_path)
        except Exception as exc:
            return {"error": f"Could not save file: {exc}"}, 500

        task_id = str(uuid.uuid4())
        add_task(task_id, account_id, video_file.filename, description, tags_raw)

        t = threading.Thread(
            target=_do_upload,
            args=(task_id, saved_path, description, tags, account["cookies"]),
            daemon=True,
        )
        t.start()

        return {"job_id": task_id, "status": Status.IN_QUEUE, "message": "Upload queued."}, 202


@ns_jobs.route("/<string:job_id>")
@ns_jobs.param("job_id", "Job UUID")
class JobDetail(Resource):
    @ns_jobs.doc("get_job")
    @ns_jobs.marshal_with(job_output)
    @ns_jobs.response(404, "Not found", error_model)
    def get(self, job_id):
        """Get job status"""
        task = get_task(job_id)
        if task is None:
            api.abort(404, "Job not found.")
        return task


# ------------------------------------------------------------------
# Legacy routes (for web dashboard compatibility)
# ------------------------------------------------------------------

@app.route("/api/upload", methods=["POST"])
def legacy_upload():
    """Proxy for web dashboard upload form."""
    from flask import request, jsonify
    if "video" not in request.files:
        return jsonify({"error": "No video file."}), 400
    video_file = request.files["video"]
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
    video_file.save(saved_path)

    task_id = str(uuid.uuid4())
    add_task(task_id, int(account_id), video_file.filename, description, tags_raw)

    t = threading.Thread(
        target=_do_upload,
        args=(task_id, saved_path, description, tags, account["cookies"]),
        daemon=True,
    )
    t.start()
    return jsonify({"task_id": task_id, "message": "Upload queued."}), 202


@app.route("/api/tasks")
def legacy_list_tasks():
    from flask import jsonify
    return jsonify(list_tasks())


@app.route("/api/status/<task_id>")
def legacy_status(task_id):
    from flask import jsonify
    task = get_task(task_id)
    if not task:
        return jsonify({"error": "Not found."}), 404
    return jsonify(task)


# ------------------------------------------------------------------
# Clipboard
# ------------------------------------------------------------------

@ns_clipboard.route("")
class Clipboard(Resource):
    clipboard_input = api.model("ClipboardInput", {
        "text": fields.String(required=True, description="Text to copy"),
    })

    @ns_clipboard.doc("set_clipboard")
    @ns_clipboard.expect(clipboard_input)
    def post(self):
        """Copy text to the container's clipboard (for VNC)"""
        text = api.payload.get("text", "")
        if not text:
            return {"error": "No text provided."}, 400
        try:
            uploader = get_uploader()
            uploader.driver.execute_cdp_cmd("Browser.grantPermissions", {
                "permissions": ["clipboardReadWrite", "clipboardSanitizedWrite"],
                "origin": uploader.driver.current_url
            })
            uploader.driver.execute_script("navigator.clipboard.writeText(arguments[0]);", text)
            return {"success": True, "message": f"Copied {len(text)} chars to clipboard."}
        except Exception as exc:
            import subprocess
            try:
                proc = subprocess.run(["xclip", "-selection", "clipboard"],
                                      input=text.encode(), timeout=5)
                if proc.returncode == 0:
                    return {"success": True, "message": f"Copied {len(text)} chars via xclip."}
            except Exception:
                pass
            return {"error": str(exc)}, 500


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=False)
