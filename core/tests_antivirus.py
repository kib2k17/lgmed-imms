"""Tests for upload virus scanning (core/antivirus.py), against a fake ClamAV daemon."""

import socketserver
import struct
import threading

from django.contrib.auth.models import AnonymousUser
from django.core.files.uploadedfile import SimpleUploadedFile
from django.http import HttpResponse
from django.test import RequestFactory, TestCase, override_settings

from audit.models import Action, AuditEvent
from core import antivirus
from core.middleware import UploadScanMiddleware

MARKER = b"EICAR-STANDARD-ANTIVIRUS-TEST-FILE"


class FakeClamd(socketserver.BaseRequestHandler):
    """Speaks just enough INSTREAM: anything containing MARKER is 'infected'."""

    received = []

    def handle(self):
        command = b""
        while not command.endswith(b"\0"):
            command += self.request.recv(1)
        data = b""
        while True:
            size = struct.unpack("!L", self._read(4))[0]
            if size == 0:
                break
            data += self._read(size)
        FakeClamd.received.append(data)
        if MARKER in data:
            self.request.sendall(b"stream: Eicar-Test-Signature FOUND\0")
        else:
            self.request.sendall(b"stream: OK\0")

    def _read(self, size):
        buffer = b""
        while len(buffer) < size:
            buffer += self.request.recv(size - len(buffer))
        return buffer


class UploadScanTests(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.server = socketserver.ThreadingTCPServer(("127.0.0.1", 0), FakeClamd)
        cls.server.daemon_threads = True
        threading.Thread(target=cls.server.serve_forever, daemon=True).start()
        cls.address = f"127.0.0.1:{cls.server.server_address[1]}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        super().tearDownClass()

    def setUp(self):
        FakeClamd.received.clear()

    def post(self, *files):
        request = RequestFactory().post(
            "/upload/", {f"file{i}": f for i, f in enumerate(files)}
        )
        request.user = AnonymousUser()
        middleware = UploadScanMiddleware(lambda r: HttpResponse("saved"))
        return middleware.process_view(request, None, (), {})

    def test_scanning_is_off_unless_configured(self):
        with override_settings(LGMED_CLAMAV_ADDRESS=""):
            self.assertIsNone(self.post(SimpleUploadedFile("a.pdf", MARKER)))
        self.assertEqual(FakeClamd.received, [])

    def test_a_clean_file_passes_and_is_scanned_whole(self):
        content = b"%PDF-1.7\n" + b"x" * (antivirus.CHUNK * 2 + 17)
        with override_settings(LGMED_CLAMAV_ADDRESS=self.address):
            self.assertIsNone(self.post(SimpleUploadedFile("a.pdf", content)))
        self.assertEqual(FakeClamd.received, [content])

    def test_an_infected_file_stops_the_request_and_is_recorded(self):
        with override_settings(LGMED_CLAMAV_ADDRESS=self.address):
            response = self.post(
                SimpleUploadedFile("clean.pdf", b"%PDF-1.7 fine"),
                SimpleUploadedFile("invoice.pdf", b"%PDF " + MARKER),
            )
        self.assertEqual(response.status_code, 422)
        self.assertIn(b"invoice.pdf", response.content)
        entry = AuditEvent.objects.get(action=Action.ACCESS_DENIED)
        self.assertIn("Eicar-Test-Signature", entry.detail)
        self.assertIn("invoice.pdf", entry.detail)

    def test_an_unreachable_scanner_is_logged_and_by_default_lets_the_file_through(self):
        with override_settings(LGMED_CLAMAV_ADDRESS="127.0.0.1:1"), \
                self.assertLogs("core.antivirus", "ERROR"):
            self.assertIsNone(self.post(SimpleUploadedFile("a.pdf", b"%PDF")))

    def test_an_unreachable_scanner_refuses_uploads_when_required(self):
        with override_settings(LGMED_CLAMAV_ADDRESS="127.0.0.1:1", LGMED_CLAMAV_REQUIRED=True), \
                self.assertLogs("core.antivirus", "ERROR"):
            response = self.post(SimpleUploadedFile("a.pdf", b"%PDF"))
        self.assertEqual(response.status_code, 503)

    def test_requests_without_files_are_not_scanned(self):
        request = RequestFactory().post("/x/", {"title": "no files"})
        request.user = AnonymousUser()
        with override_settings(LGMED_CLAMAV_ADDRESS=self.address):
            self.assertIsNone(UploadScanMiddleware(lambda r: None).process_view(request, None, (), {}))
        self.assertEqual(FakeClamd.received, [])
