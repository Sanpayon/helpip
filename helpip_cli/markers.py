# SPDX-License-Identifier: MIT
"""PEP 508 environment markers for the current interpreter."""
from __future__ import annotations

from typing import Optional

from packaging.markers import InvalidMarker, Marker, default_environment


def build_env() -> dict:
    """The PEP 508 marker environment for the current Python interpreter.

    Yields the keys the JS ``marker-environment.js`` builds
    (``python_version``, ``python_full_version``, ``os_name``, ``sys_platform``,
    ``platform_machine``, ``platform_system``, ``platform_release``,
    ``implementation_name``, ``implementation_version``,
    ``platform_python_implementation``).
    """
    return default_environment()


def should_include(requirement_str: str, env: Optional[dict]) -> bool:
    """Whether a requirement applies under ``env``.

    No ``;`` marker -> always included. A failing/empty marker -> included
    (matches the JS ``includeOnError``/``includeOnError: true`` fallback so
    transitive metadata is not dropped on a parsing hiccup).
    """
    if not isinstance(requirement_str, str):
        return True
    idx = requirement_str.find(";")
    if idx < 0:
        return True
    marker_text = requirement_str[idx + 1:].strip()
    if not marker_text:
        return True
    try:
        return bool(Marker(marker_text).evaluate(env))
    except (InvalidMarker, Exception):  # noqa: BLE001
        return True
