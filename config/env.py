"""
Where this deployment's secrets come from.

No key is ever written into ``settings.py``: that file is committed, so a value
placed in it lives in the repository history for good and shows up in every
traceback and screen share of the file. Secrets are read from the process
environment instead.

The environment alone is awkward on a development machine, though. A Django
server is very often started by running ``venv/Scripts/python.exe manage.py
runserver`` directly - from VS Code, a shortcut, a task runner - which never
executes the activation script that would have set those variables. So the
environment is topped up from a plain ``key=value`` file kept inside the
virtualenv itself:

    <venv>/lgmed.env

``sys.prefix`` points at the virtualenv whenever its interpreter is the one
running, activated or not, so the file is found either way. ``venv/`` is
excluded by ``.gitignore``, so the file never reaches the repository - and it
is deleted along with the virtualenv, so a rebuilt environment needs it written
again (see the README).

Real environment variables always win over the file. That is what lets a
production host set them the ordinary way and ignore all of this.
"""

import os
import socket
import sys
from pathlib import Path

ENV_FILENAME = "lgmed.env"


def venv_env_path() -> Path:
    """The secrets file belonging to the interpreter that is running."""
    return Path(sys.prefix) / ENV_FILENAME


def load_venv_env(path: Path | None = None) -> list[str]:
    """
    Copy ``<venv>/lgmed.env`` into ``os.environ`` and return the names read.

    Never raises: a missing or unreadable file simply means the process runs on
    whatever the real environment provides.
    """
    path = path or venv_env_path()
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return []

    names = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):          # tolerate a shell-style file
            line = line[len("export "):].lstrip()

        name, separator, value = line.partition("=")
        name = name.strip()
        if not separator or not name:
            continue

        value = value.strip()
        # Strip one matched pair of quotes, so a value with trailing spaces or
        # a '#' can still be written plainly.
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]

        os.environ.setdefault(name, value)      # the real environment wins
        names.append(name)

    return names


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def env_bool(name: str, default: bool = False) -> bool:
    raw = env(name, "1" if default else "0").lower()
    return raw in {"1", "true", "yes", "on"}


def env_float(name: str, default: float) -> float:
    try:
        return float(env(name, str(default)))
    except ValueError:
        # A typo in the file must not take the whole site down at import time.
        return default


def env_list(name: str, default: str = "") -> list[str]:
    """A comma-separated variable, split and cleaned of blanks."""
    return [part.strip() for part in env(name, default).split(",") if part.strip()]


def local_ipv4_addresses() -> list[str]:
    """
    Every IPv4 address this machine currently answers on.

    The address a colleague types into their browser is handed out by DHCP, so
    it changes when the lease expires, when the laptop rejoins, and whenever it
    moves between office networks. Writing it into a settings file means that
    file is wrong by the following morning - and the symptom, a bare 400
    "Invalid HTTP_HOST header", says nothing about which of the two addresses
    is stale. Asking the machine is the only answer that stays true.

    Two sources, because neither is sufficient alone. The host lookup finds
    every adapter, including one that is up but not carrying the default route;
    the UDP socket finds the address the default route actually uses, which is
    the one the host lookup misses on a machine whose name does not resolve.
    No packet is ever sent - a datagram socket only has to pick a local
    interface for the route to answer.

    Loopback and APIPA (169.254.x, the address Windows invents when DHCP fails)
    are dropped: neither is reachable from another machine, and listing them
    would only make a broken network look configured.
    """
    found: list[str] = []

    try:
        found.extend(socket.gethostbyname_ex(socket.gethostname())[2])
    except OSError:
        pass                                    # no name resolution; the socket below still works

    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("10.255.255.255", 1))    # unroutable on purpose; nothing is transmitted
        found.append(probe.getsockname()[0])
    except OSError:
        pass                                    # no network at all - then there is nothing to share
    finally:
        probe.close()

    addresses: list[str] = []
    for address in found:
        if address.startswith(("127.", "169.254.")) or address in addresses:
            continue
        addresses.append(address)
    return addresses
