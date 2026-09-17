"""Check running local services without creating accounts or publishing videos."""
import json
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen


def request(url, headers=None, data=None):
    try:
        with urlopen(Request(url, headers=headers or {}, data=data), timeout=120) as response:
            return response.status, response.read()
    except HTTPError as error:
        return error.code, error.read()


if __name__ == "__main__":
    config = json.loads((Path.home() / ".config/tiktok-uploader/local.json").read_text())
    for url in ("http://127.0.0.1:5050/api/accounts",
                "http://127.0.0.1:5050/api/auth/setup",
                "http://127.0.0.1:5051/api/accounts"):
        assert request(url)[0] == 401, url
    assert request("http://127.0.0.1:5051/api/accounts",
                   {"Origin": "https://untrusted.example"}, b"{}")[0] == 403
    headers = {"Authorization": "Bearer " + config["API_SECRET"]}
    status, body = request("http://127.0.0.1:5050/api/health", headers)
    assert status == 200 and json.loads(body)["alive"] is True
    assert request("http://127.0.0.1:5050/api/jobs", headers)[0] == 200
    assert request("http://127.0.0.1:5051/")[0] == 200
    print("PASS: API authentication, dashboard authentication, cross-origin rejection, live Chrome, jobs API, web page; no publication requests.")
