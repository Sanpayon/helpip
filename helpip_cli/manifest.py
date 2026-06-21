# SPDX-License-Identifier: MIT
"""Load and query ``dependencies_metadata.json`` (the AI-package manifest)."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional


def load(path: Path) -> Optional[dict]:
    """Load the manifest dict, or None if missing/invalid."""
    if not path.exists():
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _packages(manifest: Optional[dict]) -> dict:
    pkgs = (manifest or {}).get("packages")
    return pkgs if isinstance(pkgs, dict) else {}


def is_ai_package(manifest: Optional[dict], name: str) -> bool:
    """A package is AI iff its lowercased name is a key in manifest["packages"]."""
    return name.lower() in _packages(manifest)


def get_max_version(manifest: Optional[dict], name: str) -> Optional[str]:
    """Return the manifest's max known version for ``name`` (None if null/missing)."""
    return _packages(manifest).get(name.lower())


def version(manifest: Optional[dict]) -> Optional[str]:
    """The manifest schema version (used by `helpip update`)."""
    v = (manifest or {}).get("version")
    return v if isinstance(v, str) else None


def last_updated(manifest: Optional[dict]) -> Optional[str]:
    v = (manifest or {}).get("last_updated")
    return v if isinstance(v, str) else None
