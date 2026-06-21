# SPDX-License-Identifier: BSD-3-Clause
"""Pip-free requirement parsing for the vendored mixology engine.

Replaces pipgrip's ``pipper.parse_req`` (which uses pip/pkg_resources) with a
small implementation based on the ``packaging`` library, so the vendored
PubGrub engine has no pip dependency.

The returned :class:`ParsedRequirement` mirrors the attribute surface that
mixology expects: ``key`` (canonical name), ``name``, ``extras`` (frozenset),
``extras_name`` (``key[extra1,extra2]``), ``specs`` (list of
``(operator, version)``), ``url`` (direct-reference URL or None), ``marker``
(a ``packaging.markers.Marker`` or None), and ``__str__``.
"""
from __future__ import annotations

from functools import lru_cache
from typing import List, Optional, Tuple

from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name


class ParsedRequirement:
    """Parsed requirement with attributes compatible with the mixology Package."""

    __slots__ = (
        "key",
        "name",
        "extras",
        "extras_name",
        "specs",
        "url",
        "marker",
        "_str",
    )

    def __init__(
        self,
        key: str,
        name: str,
        extras: frozenset,
        extras_name: str,
        specs: List[Tuple[str, str]],
        url: Optional[str],
        marker,
        full_str: str,
    ) -> None:
        self.key = key
        self.name = name
        self.extras = extras
        self.extras_name = extras_name
        self.specs = specs
        self.url = url
        self.marker = marker
        self._str = full_str

    def __str__(self) -> str:
        return self._str


def _canonical(key: str, extras: frozenset) -> str:
    if not extras:
        return key
    return "{}[{}]".format(key, ",".join(sorted(extras)))


@lru_cache(maxsize=4096)
def parse_req(requirement: str, extras: Optional[frozenset] = None) -> ParsedRequirement:
    """Parse a PEP 508 requirement string into a :class:`ParsedRequirement`.

    The special root marker ``"_root_"`` (used by mixology) parses to a benign
    placeholder requirement.
    """
    extras = extras or frozenset()

    if requirement == "_root_":
        key = "_root_"
        return ParsedRequirement(
            key=key,
            name=key,
            extras=frozenset(),
            extras_name=key,
            specs=[],
            url=None,
            marker=None,
            full_str=key,
        )

    try:
        parsed = Requirement(requirement)
    except InvalidRequirement as exc:
        raise InvalidRequirement("Invalid requirement {!r}: {}".format(requirement, exc))

    key = canonicalize_name(parsed.name)
    extras_frozen = frozenset(extras or parsed.extras)
    extras_name = _canonical(key, extras_frozen)
    specs = [(spec.operator, spec.version) for spec in parsed.specifier]
    # Rebuild a clean string so str() is stable regardless of input formatting.
    full_str = str(parsed)

    return ParsedRequirement(
        key=key,
        name=key,
        extras=extras_frozen,
        extras_name=extras_name,
        specs=specs,
        url=parsed.url,
        marker=parsed.marker,
        full_str=full_str,
    )
