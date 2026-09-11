import csv
import http.client
import json
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from attendance_web import Attendance, CheckinError, Server


class AttendanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "scores.csv"
        self.names = ["Ada Example", "Bo Example", "Chen Example"]
        self.state = Attendance(self.path, "Lab-P2 (123)", self.names, 10)

    def test_closed_then_open_and_history_persist(self):
        with self.assertRaises(CheckinError) as error:
            self.state.check_in(0)
        self.assertEqual(error.exception.status, 403)
        self.state.is_open = True
        self.state.check_in(0)
        self.assertEqual([r[self.state.column] for r in self.state.read_rows()], ["10", "0", "0"])
        self.state.check_in(1)
        restarted = Attendance(self.path, self.state.column, self.names, 10)
        self.assertFalse(restarted.is_open)
        self.assertEqual(restarted.status()["count"], 2)
        self.assertEqual(restarted.status()["submissions"][0]["name"], self.names[1])
        self.assertEqual(restarted.read_rows()[0][self.state.column], "10")

    def test_same_student_can_check_in_again(self):
        self.state.is_open = True
        self.state.check_in(0)
        self.state.check_in(0)
        status = self.state.status()
        self.assertEqual(status["count"], 2)
        self.assertEqual(status["unique_count"], 1)

    def test_concurrent_students_do_not_lose_scores(self):
        self.state.is_open = True
        with ThreadPoolExecutor(max_workers=3) as pool:
            results = list(pool.map(self.state.check_in, range(3)))
        self.assertEqual(results, self.names)
        self.assertTrue(all(row[self.state.column] == "10" for row in self.state.read_rows()))

    def test_old_browser_history_is_preserved(self):
        with sqlite3.connect(self.state.db_path) as db:
            db.execute("INSERT INTO receipts (lab, device, name) VALUES (?, ?, ?)",
                       (self.state.column, "old-browser-id", self.names[0]))
        restarted = Attendance(self.path, self.state.column, self.names, 10)
        restarted.is_open = True
        restarted.check_in(1)
        self.assertEqual(restarted.status()["count"], 2)
        self.assertEqual({row["name"] for row in restarted.status()["submissions"]}, set(self.names[:2]))

    def test_close_rejects_next_student(self):
        self.state.is_open = True
        self.state.check_in(0)
        self.state.is_open = False
        before = self.path.read_bytes()
        with self.assertRaises(CheckinError) as error:
            self.state.check_in(1)
        self.assertEqual(error.exception.status, 403)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.state.status()["count"], 1)

    def test_failed_save_does_not_add_history(self):
        before = self.path.read_bytes()
        self.state.is_open = True
        with patch("attendance_web.os.replace", side_effect=OSError("disk error")):
            with self.assertRaises(OSError):
                self.state.check_in(0)
        self.assertEqual(self.path.read_bytes(), before)
        self.assertEqual(self.state.status()["count"], 0)
        self.state.check_in(0)

    def test_changed_order_and_existing_scores_preserved(self):
        rows = self.state.read_rows()[::-1]
        rows[0][self.state.column] = "5"
        self.state.save_rows(rows)
        self.state.is_open = True
        self.state.check_in(0)
        self.assertEqual([r[self.state.column] for r in self.state.read_rows()], ["5", "0", "10"])

    def test_invalid_student_does_not_change_file(self):
        self.state.is_open = True
        before = self.path.read_bytes()
        for invalid in (-1, 3, True, "0", None):
            with self.assertRaises(CheckinError):
                self.state.check_in(invalid)
        self.assertEqual(self.path.read_bytes(), before)

    def test_merge_with_canvas_preserves_other_columns(self):
        source = Path(self.temp.name) / "source.csv"
        output = Path(self.temp.name) / "import.csv"
        with source.open("w", newline="") as handle:
            writer = csv.writer(handle)
            writer.writerow(["Student", "ID", "Section", self.state.column, "Other (456)"])
            writer.writerow(["Points Possible", "", "", "10", "20"])
            for index, name in enumerate(self.names):
                writer.writerow([name, str(index + 1), "Lab 1", "", "7.5"])
        self.state.is_open = True
        self.state.check_in(1)
        result = subprocess.run([
            sys.executable, str(Path(__file__).with_name("lab.py")), "merge",
            "--source", str(source), "--scores", str(self.path), "--output", str(output),
        ], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        with output.open(newline="") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual([r[self.state.column] for r in rows], ["10", "0", "10", "0"])
        self.assertEqual([r["Other (456)"] for r in rows], ["20", "7.5", "7.5", "7.5"])


class HTTPTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.state = Attendance(Path(self.temp.name) / "scores.csv", "Lab-P2 (123)", ["Ada", "Bo"], 10)
        self.server = Server(("127.0.0.1", 0), self.state)
        self.port = self.server.server_port
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.stop)

    def stop(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def request(self, path, method="GET", body=None, headers=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=5)
        try:
            conn.request(method, path, body=body, headers=headers or {})
            response = conn.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            conn.close()

    def test_http_end_to_end_and_admin_protection(self):
        status, headers, body = self.request("/api/session")
        self.assertEqual(status, 200)
        self.assertFalse(json.loads(body)["open"])
        self.assertNotIn("Set-Cookie", headers)
        self.assertFalse(json.loads(body)["can_manage"])
        student = {"Content-Type": "application/json", "Cookie": "attendance_device=old-cookie"}
        admin = {"Content-Type": "application/json", "Authorization": "Bearer " + self.state.admin_token}
        self.assertEqual(self.request("/api/admin/open", "POST", "{}", student)[0], 401)
        self.assertEqual(self.request("/api/admin")[0], 401)
        self.assertEqual(self.request("/scores.csv")[0], 404)
        self.assertEqual(self.request("/../lab.py")[0], 404)
        self.assertEqual(self.request("/api/checkin", "POST", '{"student_id":0}', student)[0], 403)
        self.assertEqual(self.request("/api/admin/open", "POST", "{}", admin)[0], 200)
        self.assertEqual(len(json.loads(self.request("/api/session", headers=student)[2])["students"]), 2)
        self.assertEqual(self.request("/api/checkin", "POST", '{"student_id":0}', student)[0], 200)
        self.assertEqual(self.request("/api/checkin", "POST", '{"student_id":1}', student)[0], 200)
        self.assertEqual(self.request("/api/checkin", "POST", '{"student_id":0}', student)[0], 200)
        session = json.loads(self.request("/api/session", headers=student)[2])
        self.assertEqual(session["count"], 3)
        self.assertEqual(session["unique_count"], 2)
        self.assertEqual([row["name"] for row in session["submissions"]], ["Ada", "Bo", "Ada"])
        self.assertEqual(len(session["students"]), 2)
        self.assertTrue(json.loads(self.request("/api/session", headers=admin)[2])["can_manage"])
        self.assertEqual(self.request("/api/admin/close", "POST", "{}", admin)[0], 200)
        self.assertEqual(self.request("/api/checkin", "POST", '{"student_id":1}', student)[0], 403)

    def test_single_page_assets_and_request_validation(self):
        self.assertEqual(self.request("/api/qr")[0], 404)
        self.assertEqual(self.request("/")[2], self.request("/admin")[2])
        for asset in ("/", "/admin", "/style.css", "/checkin.js"):
            self.assertEqual(self.request(asset)[0], 200)
        self.assertEqual(self.request("/api/checkin", "POST", "student_id=0")[0], 415)
        headers = {"Content-Type": "application/json"}
        self.assertEqual(self.request("/api/checkin", "POST", "[]", headers)[0], 400)
        self.state.is_open = True
        self.assertEqual(self.request("/api/checkin", "POST", "{}", headers)[0], 400)

    def test_checkin_works_without_cookies_and_returns_updated_history(self):
        self.state.is_open = True
        for index in (0, 1):
            status, _, body = self.request("/api/checkin", "POST", json.dumps({"student_id": index}),
                                           {"Content-Type": "application/json"})
            self.assertEqual(status, 200)
            result = json.loads(body)
            self.assertEqual(result["session"]["count"], index + 1)
            self.assertEqual(result["session"]["submissions"][0]["name"], result["name"])
            self.assertEqual(result["score"], 10)


if __name__ == "__main__":
    unittest.main()
