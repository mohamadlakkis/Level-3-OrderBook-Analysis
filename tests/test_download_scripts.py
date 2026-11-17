"""Real download/resume tests, runnable with only the Python standard library.

Ubuntu runs the macOS Bash script with real curl. Native macOS and Windows CI
jobs run the appropriate script on those operating systems. No Nasdaq download
or third-party Python packages are needed for these tests.
"""

from __future__ import annotations

import gzip
import os
import shutil
import subprocess
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import ClassVar

PROJECT = Path(__file__).resolve().parents[1]
FILENAME = "12302019.NASDAQ_ITCH50.gz"
PAYLOAD = gzip.compress(b"tiny test fixture\n" + bytes(range(256)) * 20, mtime=0)


class _FileHandler(BaseHTTPRequestHandler):
    """Serve gzip bytes, redirects, HTTP errors, and byte-range resume responses."""

    requests: ClassVar[list[tuple[str, str | None]]] = []

    def do_GET(self) -> None:
        """Return the fixture or an explicitly requested error; record resume headers."""
        requested_range = self.headers.get("Range")
        self.requests.append((self.path, requested_range))
        if self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "/file")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if self.path not in ("/file", "/no-range"):
            self.send_response(404)
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        if self.path == "/no-range":
            requested_range = None  # Simulate a server that cannot resume a transfer.
        start = (
            int(requested_range.removeprefix("bytes=").removesuffix("-")) if requested_range else 0
        )
        if requested_range and start >= len(PAYLOAD):
            self.send_response(416)
            self.send_header("Content-Range", f"bytes */{len(PAYLOAD)}")
            self.send_header("Content-Length", "0")
            self.end_headers()
            return
        self.send_response(206 if requested_range else 200)
        self.send_header("Accept-Ranges", "bytes")
        self.send_header("Content-Length", str(len(PAYLOAD) - start))
        if requested_range:
            self.send_header("Content-Range", f"bytes {start}-{len(PAYLOAD) - 1}/{len(PAYLOAD)}")
        self.end_headers()
        self.wfile.write(PAYLOAD[start:])

    def log_message(self, format: str, *args: object) -> None:
        """Suppress routine HTTP logs; subprocess output is shown on failed assertions."""


class DownloadScriptTests(unittest.TestCase):
    """Exercise the real platform downloader in an isolated project with spaces."""

    def setUp(self) -> None:
        """Create a disposable project, unrelated working directory, and HTTP server."""
        self.temporary = tempfile.TemporaryDirectory(prefix="itch download tests ")
        self.addCleanup(self.temporary.cleanup)
        root = Path(self.temporary.name)
        self.project = root / "project with spaces"
        self.project.mkdir()
        self.cwd = root / "unrelated working directory"
        self.cwd.mkdir()
        self.destination = self.project / "data" / "raw" / FILENAME
        if os.name == "nt":
            shell = shutil.which("powershell.exe") or shutil.which("pwsh")
            if shell is None or shutil.which("curl.exe") is None:
                self.fail("Windows download tests require PowerShell and curl.exe.")
            script = self.project / "windows_setup.ps1"
            shutil.copyfile(PROJECT / script.name, script)
            self.command = [shell, "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)]
        else:
            shell = shutil.which("bash")
            if shell is None or shutil.which("curl") is None:
                self.fail("Download tests require Bash and curl.")
            script = self.project / "macos_setup.sh"
            shutil.copyfile(PROJECT / script.name, script)
            self.command = [shell, str(script)]
        _FileHandler.requests = []
        server = ThreadingHTTPServer(("127.0.0.1", 0), _FileHandler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join)
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.url = f"http://127.0.0.1:{server.server_port}"

    def run_script(self, endpoint: str) -> subprocess.CompletedProcess[str]:
        """Run the actual downloader against the local fixture and capture diagnostics."""
        return subprocess.run(
            [*self.command, f"{self.url}/{endpoint}"],
            cwd=self.cwd,
            env={**os.environ, "NO_PROXY": "127.0.0.1", "no_proxy": "127.0.0.1"},
            capture_output=True,
            text=True,
            timeout=30,
        )

    def test_download_from_another_directory(self) -> None:
        """Create root data/raw even with spaces, while retaining exact gzip bytes."""
        result = self.run_script("file")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.destination.read_bytes(), PAYLOAD)
        self.assertTrue(gzip.decompress(self.destination.read_bytes()))
        self.assertFalse((self.cwd / "data").exists())

    def test_resume_partial_download(self) -> None:
        """Send a Range request and append only the missing bytes."""
        prefix_size = len(PAYLOAD) // 2
        self.destination.parent.mkdir(parents=True)
        self.destination.write_bytes(PAYLOAD[:prefix_size])
        result = self.run_script("file")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.destination.read_bytes(), PAYLOAD)
        self.assertIn(("/file", f"bytes={prefix_size}-"), _FileHandler.requests)

    def test_completed_download_is_preserved(self) -> None:
        """An EOF resume rejected with HTTP 416 must leave the complete file intact."""
        self.destination.parent.mkdir(parents=True)
        self.destination.write_bytes(PAYLOAD)
        result = self.run_script("file")
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("416", result.stderr)
        self.assertEqual(self.destination.read_bytes(), PAYLOAD)

    def test_follows_redirects(self) -> None:
        """A mirror redirect must produce the file contents rather than an HTML page."""
        result = self.run_script("redirect")
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.destination.read_bytes(), PAYLOAD)

    def test_http_failure_preserves_partial_download(self) -> None:
        """HTTP errors must return nonzero and leave existing bytes available to resume."""
        prefix = PAYLOAD[:20]
        self.destination.parent.mkdir(parents=True)
        self.destination.write_bytes(prefix)
        result = self.run_script("missing")
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.destination.read_bytes(), prefix)

    def test_oversized_existing_file_is_not_reported_complete(self) -> None:
        """An oversized existing file must fail and retain its original bytes."""
        original = PAYLOAD + b"unexpected extra bytes"
        self.destination.parent.mkdir(parents=True)
        self.destination.write_bytes(original)
        result = self.run_script("file")
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.destination.read_bytes(), original)

    def test_server_without_resume_support_preserves_partial_file(self) -> None:
        """Do not silently append a whole response to an existing partial file."""
        original = PAYLOAD[:20]
        self.destination.parent.mkdir(parents=True)
        self.destination.write_bytes(original)
        result = self.run_script("no-range")
        self.assertNotEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertEqual(self.destination.read_bytes(), original)
