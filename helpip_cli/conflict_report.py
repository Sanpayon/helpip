# SPDX-License-Identifier: MIT
"""Conflict/warning report types and rendering.

The PubGrub engine's ``SolverFailure`` already produces a rich, multi-line
explanation that names the conflicting packages and versions. We surface that
text directly (it is more informative than the JS extension's single-line
messages) and, for ``-r``, also point at the offending file line when the
failing package can be matched back to an input entry.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable, Optional

from helpip_cli.parsing import Entry
from helpip_cli.resolver import ResolveResult

# Patterns ported from diagnostics.js _extractConflictPackages (PubGrub/mixology
# phrasing). Used to map a conflict back to an input line for `-r`.
_CONFLICT_PATTERNS = [
    re.compile(r'"([A-Za-z0-9_.\-\[\]+]+)"\s+which doesn\'t match'),
    re.compile(r'depends on\s+"([A-Za-z0-9_.\-\[\]+]+)"'),
    re.compile(r'"([A-Za-z0-9_.\-\[\]+]+)"\s+is\s+forbidden'),
    re.compile(r'"([A-Za-z0-9_.\-\[\]+]+)"\s+requires'),
    re.compile(r'"([A-Za-z0-9_.\-\[\]+]+)"\s+is\s+incompatible'),
]


@dataclass
class WarningItem:
    package_name: str
    message: str
    line_index: Optional[int] = None


@dataclass
class ConflictItem:
    package_name: Optional[str]
    message: str
    line_index: Optional[int] = None


@dataclass
class ConflictReport:
    conflicts: list[ConflictItem] = field(default_factory=list)
    warnings: list[WarningItem] = field(default_factory=list)

    @property
    def has_conflict(self) -> bool:
        return bool(self.conflicts)


def extract_conflict_packages(message: str) -> list[str]:
    found: list[str] = []
    seen: set[str] = set()
    for pat in _CONFLICT_PATTERNS:
        for m in pat.finditer(message or ""):
            name = m.group(1)
            if name not in seen:
                seen.add(name)
                found.append(name)
    return found


def _match_entry(name: str, entries: Iterable[Entry]) -> Optional[Entry]:
    target = name.lower()
    for e in entries:
        if e.package_name.lower() == target:
            return e
    return None


def build(
    result: ResolveResult,
    ai_entries: list[Entry],
    *,
    has_line_index: bool,
) -> tuple[list[ConflictItem], list[WarningItem]]:
    """Turn a ResolveResult into conflict items.

    ``has_line_index`` is True for ``-r`` (so we attach the offending line) and
    False for ``-i`` (no line info).
    """
    conflicts: list[ConflictItem] = []
    if not result.error:
        return conflicts, []

    message = result.message or "version solving failed"
    line_index: Optional[int] = None
    target_name: Optional[str] = None
    if has_line_index:
        for name in extract_conflict_packages(message):
            entry = _match_entry(name, ai_entries)
            if entry is not None:
                target_name = entry.package_name
                line_index = entry.line_index
                break
    conflicts.append(ConflictItem(package_name=target_name, message=message, line_index=line_index))
    return conflicts, []
