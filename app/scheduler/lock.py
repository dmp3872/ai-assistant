"""Exclusive file lock so two 45-minute runs never overlap."""
from __future__ import annotations

import os
from pathlib import Path


class LockHeld(RuntimeError):
    pass


class FileLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self._fd: int | None = None

    def __enter__(self) -> "FileLock":
        try:
            # O_EXCL makes creation atomic; fails if a run is already in progress
            self._fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.write(self._fd, str(os.getpid()).encode())
            return self
        except FileExistsError:
            raise LockHeld(f"Another run holds {self.path}")

    def __exit__(self, *exc) -> None:
        if self._fd is not None:
            os.close(self._fd)
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass
