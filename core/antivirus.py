"""
Virus scanning of uploads with ClamAV - off unless configured.

Every module takes files from LGUs and the public, and staff open them on
their own computers. core/uploads.py stops a file that lies about its type;
it cannot tell a malicious PDF or a macro-laden spreadsheet from a clean one
(SECURITY_AUDIT.md, M-09). A ClamAV daemon can, and this talks to one directly
over its INSTREAM protocol, so no Python package is needed.

    LGMED_CLAMAV_ADDRESS   "host:port" (TCP, e.g. 127.0.0.1:3310) or
                           "unix:/run/clamav/clamd.ctl"; empty = no scanning
    LGMED_CLAMAV_TIMEOUT   seconds to wait for a verdict (default 30)
    LGMED_CLAMAV_REQUIRED  1 = refuse uploads while the scanner cannot be
                           reached; 0 (default) = accept them and log an error

Scanning happens once per request, for every file in it, before any view runs
(core.middleware.UploadScanMiddleware) - so a module added later is covered
without having to remember to call anything.
"""

import logging
import socket
import struct
from dataclasses import dataclass

from django.conf import settings

logger = logging.getLogger(__name__)

CHUNK = 64 * 1024


class ScannerUnavailable(Exception):
    """The daemon could not be reached or gave no usable answer."""


@dataclass(frozen=True)
class Verdict:
    clean: bool
    signature: str = ""


def is_enabled():
    return bool(getattr(settings, "LGMED_CLAMAV_ADDRESS", ""))


def _connect():
    address = settings.LGMED_CLAMAV_ADDRESS
    timeout = getattr(settings, "LGMED_CLAMAV_TIMEOUT", 30)
    try:
        if address.startswith("unix:"):
            sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            sock.settimeout(timeout)
            sock.connect(address[len("unix:"):])
            return sock
        host, _, port = address.rpartition(":")
        return socket.create_connection((host or "127.0.0.1", int(port)), timeout=timeout)
    except (OSError, ValueError, AttributeError) as exc:
        raise ScannerUnavailable(f"cannot reach ClamAV at {address}: {exc}") from exc


def scan(uploaded):
    """
    Stream one uploaded file to ClamAV. Returns a Verdict; raises
    ScannerUnavailable when there is no answer to be had.
    """
    position = uploaded.tell() if hasattr(uploaded, "tell") else 0
    uploaded.seek(0)
    sock = _connect()
    try:
        sock.sendall(b"zINSTREAM\0")
        while True:
            chunk = uploaded.read(CHUNK)
            if not chunk:
                break
            sock.sendall(struct.pack("!L", len(chunk)) + chunk)
        sock.sendall(struct.pack("!L", 0))
        reply = b""
        while not reply.endswith(b"\0"):
            part = sock.recv(4096)
            if not part:
                break
            reply += part
    except OSError as exc:
        raise ScannerUnavailable(f"ClamAV stopped answering: {exc}") from exc
    finally:
        sock.close()
        uploaded.seek(position)

    answer = reply.rstrip(b"\0").decode("utf-8", "replace").strip()
    # "stream: OK" | "stream: <signature> FOUND" | "<message> ERROR"
    if answer.endswith(" OK"):
        return Verdict(clean=True)
    if answer.endswith(" FOUND"):
        signature = answer.split(":", 1)[-1].rsplit(" ", 1)[0].strip()
        return Verdict(clean=False, signature=signature)
    raise ScannerUnavailable(f"ClamAV could not scan the file: {answer or 'no reply'}")
