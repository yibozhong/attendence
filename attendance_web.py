"""Local classroom check-in server; only explicitly listed routes are served."""

import csv
import json
import math
import os
import secrets
import sqlite3
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit


WEB_DIR = Path(__file__).with_name("web")


def name_key(name):
    return " ".join(name.strip().casefold().split())


class CheckinError(Exception):
    def __init__(self, status, message):
        self.status = status
        super().__init__(message)


class Attendance:
    def __init__(self, path, column, names, max_points):
        self.path = Path(path).resolve()
        self.column = column
        self.names = names
        self.max_points = max_points
        self.lock = threading.RLock()
        self.is_open = False
        self.admin_token = secrets.token_urlsafe(32)
        self.db_path = self.path.with_suffix(self.path.suffix + ".sqlite3")
        if not self.path.exists():
            with self.path.open("x", encoding="utf-8", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(["Student", column])
                writer.writerows((name, "0") for name in names)
        self.read_rows()
        with sqlite3.connect(self.db_path) as db:
            db.execute("""CREATE TABLE IF NOT EXISTS receipts (
                lab TEXT NOT NULL, device TEXT NOT NULL, name TEXT NOT NULL,
                created TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (lab, device))""")

    def read_rows(self):
        with self.path.open(encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            if reader.fieldnames != ["Student", self.column]:
                raise ValueError("Attendance columns do not match this Lab")
            rows = list(reader)
        keys = [name_key(row["Student"]) for row in rows]
        if len(keys) != len(set(keys)) or set(keys) != {name_key(n) for n in self.names}:
            raise ValueError("Attendance roster does not match the source")
        for row in rows:
            try:
                score = float(row[self.column])
            except (TypeError, ValueError):
                raise ValueError("Invalid attendance score") from None
            if None in row or not math.isfinite(score) or not 0 <= score <= self.max_points:
                raise ValueError("Invalid attendance score or CSV row")
        return rows

    def save_rows(self, rows):
        # Replace the file only after a complete CSV has reached disk.
        temp_path = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", newline="", dir=self.path.parent,
                prefix=".attendance-", suffix=".csv", delete=False,
            ) as handle:
                temp_path = Path(handle.name)
                writer = csv.DictWriter(handle, fieldnames=["Student", self.column])
                writer.writeheader()
                writer.writerows(rows)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, self.path)
        finally:
            if temp_path is not None:
                temp_path.unlink(missing_ok=True)

    def check_in(self, student_id):
        with self.lock, sqlite3.connect(self.db_path) as db:
            if not self.is_open:
                raise CheckinError(403, "Check-in is closed. Please contact your instructor.")
            if type(student_id) is not int or not 0 <= student_id < len(self.names):
                raise CheckinError(400, "Please select your name from the roster.")
            # Serialize history and CSV writes, including other processes.
            db.execute("BEGIN IMMEDIATE")
            name = self.names[student_id]
            rows = self.read_rows()
            for row in rows:
                if name_key(row["Student"]) == name_key(name):
                    row[self.column] = "10"
            db.execute(
                "INSERT INTO receipts (lab, device, name) VALUES (?, ?, ?)",
                # Keep the existing history schema; device is now a submission ID.
                (self.column, secrets.token_urlsafe(32), name),
            )
            self.save_rows(rows)
        return name

    def status(self):
        with self.lock, sqlite3.connect(self.db_path) as db:
            submissions = db.execute(
                "SELECT name, created FROM receipts WHERE lab = ? ORDER BY created DESC, rowid DESC",
                (self.column,),
            ).fetchall()
            return {
                "lab": self.column.rsplit(" (", 1)[0], "open": self.is_open,
                "total": len(self.names),
                "students": [
                    {"id": index, "name": name} for index, name in enumerate(self.names)
                ] if self.is_open else [],
                "count": len(submissions), "unique_count": len({r[0] for r in submissions}),
                "submissions": [{"name": n, "time": t + "Z"} for n, t in submissions],
            }


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, attendance):
        self.attendance = attendance
        super().__init__(address, Handler)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        # Avoid logging student names and credentials.
        pass

    def reply(self, status, body, content_type="application/json; charset=utf-8"):
        if isinstance(body, dict):
            body = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; frame-ancestors 'none'; base-uri 'none'")
        self.end_headers()
        self.wfile.write(body)

    def is_admin(self):
        expected = "Bearer " + self.server.attendance.admin_token
        return secrets.compare_digest(self.headers.get("Authorization", "").encode(), expected.encode())

    def require_admin(self):
        if not self.is_admin():
            raise CheckinError(401, "Invalid admin link. Please use the complete admin URL shown in the terminal.")

    def session(self):
        return {**self.server.attendance.status(), "can_manage": self.is_admin()}

    def do_GET(self):
        try:
            state = self.server.attendance
            path = urlsplit(self.path).path
            assets = {
                "/": ("index.html", "text/html; charset=utf-8"),
                "/admin": ("index.html", "text/html; charset=utf-8"),
                "/style.css": ("style.css", "text/css; charset=utf-8"),
                "/checkin.js": ("checkin.js", "text/javascript; charset=utf-8"),
            }
            if path in assets:
                filename, content_type = assets[path]
                self.reply(200, (WEB_DIR / filename).read_bytes(), content_type)
            elif path == "/api/session":
                self.reply(200, self.session())
            elif path == "/api/admin":
                self.require_admin()
                self.reply(200, self.session())
            else:
                self.reply(404, {"error": "Page not found."})
        except CheckinError as error:
            self.reply(error.status, {"error": str(error)})
        except (OSError, ValueError, sqlite3.Error):
            self.reply(500, {"error": "Could not read attendance data. Please ask your instructor to check the files."})

    def do_POST(self):
        try:
            state = self.server.attendance
            path = urlsplit(self.path).path
            if path not in {"/api/checkin", "/api/admin/open", "/api/admin/close"}:
                raise CheckinError(404, "Page not found.")
            if path.startswith("/api/admin/"):
                self.require_admin()
            # JSON-only requests prevent cross-origin HTML forms from changing state.
            if self.headers.get_content_type() != "application/json":
                raise CheckinError(415, "Please submit through the check-in page.")
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 4096:
                    raise ValueError()
                body = json.loads(self.rfile.read(size))
                if not isinstance(body, dict):
                    raise ValueError()
            except (ValueError, UnicodeError):
                raise CheckinError(400, "Invalid submission format.") from None
            if path == "/api/checkin":
                with state.lock:
                    name = state.check_in(body.get("student_id"))
                    self.reply(200, {"name": name, "score": 10, "session": self.session()})
            else:
                with state.lock:
                    state.is_open = path.endswith("/open")
                    self.reply(200, self.session())
        except CheckinError as error:
            self.reply(error.status, {"error": str(error)})
        except (OSError, ValueError, sqlite3.Error):
            self.reply(500, {"error": "Could not save your check-in. Please ask your instructor to check the CSV and try again."})


def serve(path, column, names, max_points, host, port):
    if not 1 <= port <= 65535:
        raise ValueError("Port must be between 1 and 65535")
    state = Attendance(path, column, names, max_points)
    with Server((host, port), state) as server:
        admin_host = "127.0.0.1" if host == "0.0.0.0" else host
        print(f"Check-in page (with instructor controls): http://{admin_host}:{port}/#{state.admin_token}", flush=True)
        print(f"Saving scores to: {state.path}", flush=True)
        print("Check-in is CLOSED. Open the link above on this computer and click Open check-in.", flush=True)
        print("Students can take turns using the same page. Press Ctrl+C to stop.", flush=True)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print("\nCheck-in server stopped. Saved scores are ready for merge.")
