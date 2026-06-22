# SPDX-License-Identifier: MIT
"""PEP 508 environment markers for the current interpreter."""
from __future__ import annotations

from functools import lru_cache
from typing import Optional

from packaging.markers import InvalidMarker, Marker, default_environment


def build_env() -> dict:
    """The PEP 508 marker environment for the current Python interpreter."""
    return default_environment()


@lru_cache(maxsize=8192)
def _eval_marker(marker_text: str, env_items: tuple) -> bool:
    """Cached marker evaluation — called per unique (text, env) pair.

    ``env_items`` is a hashable representation of the marker environment
    (normally ``tuple(sorted(env.items()))``).
    """
    env = dict(env_items)
    try:
        return bool(Marker(marker_text).evaluate(env))
    except (InvalidMarker, Exception):  # noqa: BLE001
        return True


def should_include(requirement_str: str, env: Optional[dict]) -> bool:
    """Whether a requirement applies under ``env``.

    No ``;`` marker -> always included. A failing/empty marker -> included
    (matches the JS ``includeOnError`` fallback).
    """
    if not isinstance(requirement_str, str):
        return True
    idx = requirement_str.find(";")
    if idx < 0:
        return True
    marker_text = requirement_str[idx + 1:].strip()
    if not marker_text:
        return True
    env_key = tuple(sorted((env or {}).items()))
    return _eval_marker(marker_text, env_key)
