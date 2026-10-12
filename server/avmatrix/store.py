"""Ablage: Konfiguration (Geräte, Sperrliste), Zustand (Sperren, Labels, Presets) und Zugangsschlüssel.

Alles liegt außerhalb des Repos:
* Konfiguration  ``$AVM_CONFIG_DIR``  (Vorgabe ``~/.config/av-matrix``):  ``config.json``, ``token`` (Rechte 600)
* Zustand        ``$AVM_DATA_DIR``    (Vorgabe ``~/.local/share/av-matrix``): ``state.json``
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import secrets
import tempfile
from pathlib import Path
from typing import Any

_LOGGER = logging.getLogger(__name__)


def config_dir() -> Path:
    return Path(os.environ.get("AVM_CONFIG_DIR") or Path.home() / ".config" / "av-matrix")


def data_dir() -> Path:
    return Path(os.environ.get("AVM_DATA_DIR") or Path.home() / ".local" / "share" / "av-matrix")


def _write_atomic(path: Path, text: str, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


class JsonFile:
    """Eine JSON-Datei mit verzögertem, atomarem Schreiben."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.data: dict[str, Any] = {}
        self._handle: asyncio.TimerHandle | None = None

    def load(self) -> dict[str, Any]:
        try:
            self.data = json.loads(self.path.read_text(encoding="utf-8"))
            if not isinstance(self.data, dict):
                raise ValueError("kein JSON-Objekt")
        except FileNotFoundError:
            self.data = {}
        except (OSError, ValueError) as err:
            # kaputte Datei nie stillschweigend überschreiben
            raise SystemExit(f"{self.path} ist nicht lesbar ({err}). Bitte reparieren oder entfernen.") from err
        return self.data

    def save_now(self) -> None:
        if self._handle is not None:
            self._handle.cancel()
            self._handle = None
        _write_atomic(self.path, json.dumps(self.data, ensure_ascii=False, indent=2) + "\n")

    def save(self, delay: float = 0.5) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            self.save_now()
            return
        if self._handle is None:
            self._handle = loop.call_later(delay, self._flush)

    def _flush(self) -> None:
        self._handle = None
        try:
            self.save_now()
        except OSError as err:
            _LOGGER.error("Konnte %s nicht schreiben: %s", self.path, err)


class TokenFile:
    """Zugangsschlüssel für schreibende MCP-Werkzeuge. Wird nie geloggt."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self._token: str | None = None

    def load_or_create(self) -> str:
        try:
            token = self.path.read_text(encoding="utf-8").strip()
        except FileNotFoundError:
            token = ""
        if len(token) < 24:
            return self.rotate()
        if (self.path.stat().st_mode & 0o777) != 0o600:
            os.chmod(self.path, 0o600)
        self._token = token
        return token

    def rotate(self) -> str:
        self._token = "avm_" + secrets.token_urlsafe(32)
        _write_atomic(self.path, self._token + "\n", 0o600)
        return self._token

    @property
    def token(self) -> str:
        return self._token or self.load_or_create()

    def check(self, candidate: str | None) -> bool:
        return bool(candidate) and secrets.compare_digest(candidate.encode(), self.token.encode())
