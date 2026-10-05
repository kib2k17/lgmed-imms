import os
import socket
import sys
from pathlib import Path

ENV_FILENAME = "lgmed.env"


def venv_env_path() -> Path:
    """The secrets file belonging to the interpreter that is running."""
    return Path(sys.prefix) / ENV_FILENAME


def load_venv_env(path: Path | None = None) -> list[str]:

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
