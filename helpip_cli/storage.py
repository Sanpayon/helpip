# SPDX-License-Identifier: MIT
"""Filesystem facade over ``$HOME/.helpip/storage``."""
from __future__ import annotations

from pathlib import Path

from helpip_cli import config


class NotInitializedError(RuntimeError):
    """Raised when a command needs the data sources but they are missing."""


class Storage:
    def __init__(self, root: Path | None = None) -> None:
        self.root = Path(root) if root is not None else config.storage_dir()

    def ensure_dir(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)

    def path(self, name: str) -> Path:
        return self.root / name

    def exists(self, name: str) -> bool:
        return self.path(name).exists()

    def missing(self) -> list[str]:
        return [name for name in config.REQUIRED_FILES if not self.exists(name)]

    def is_initialized(self) -> bool:
        return not self.missing()

    def require_initialized(self) -> None:
        missing = self.missing()
        if missing:
            raise NotInitializedError(
                "helpip is not initialized. Missing data sources: "
                + ", ".join(missing)
                + ". Run `helpip init` first."
            )
