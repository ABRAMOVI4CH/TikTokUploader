"""Exercise a separate real Chrome session; no TikTok requests or user data."""
import tempfile
from pathlib import Path

import db


if __name__ == "__main__":
    with tempfile.TemporaryDirectory() as directory:
        db.DB_PATH = str(Path(directory) / "check.db")
        from api import server

        try:
            with server.get_uploader() as uploader:
                uploader.driver.get("data:text/html,<title>before close</title>")
                assert uploader.driver.title == "before close"
                uploader.driver.close()
            with server.get_uploader() as uploader:
                uploader.driver.get("data:text/html,<title>recovered</title>")
                assert uploader.driver.title == "recovered"
            attempts = []
            try:
                with server.get_uploader() as uploader:
                    attempts.append("started")
                    raise RuntimeError("interrupted operation")
            except RuntimeError as error:
                assert str(error) == "interrupted operation"
            else:
                raise AssertionError("Operation failure was swallowed")
            assert attempts == ["started"]
            with server.get_uploader() as uploader:
                assert uploader.driver.title == "recovered"
            print("PASS: closed Chrome recreated, page usable, failed operation not replayed, lock released.")
        finally:
            if server._uploader is not None:
                server._uploader.quit()
