# SPDX-License-Identifier: MIT
"""Orchestrator: DB filter -> AI filter -> version-before-pubgrub -> resolve.

Faithful to ``vscode-extension/lsp/diagnostics.js``'s flow. The CLI always
takes the JS ``hasUptodate=true`` branch for the version-before-pubgrub check:
warn + splice, no remote download (``update``/``upgrade`` are the explicit
network commands).
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from helpip_cli import config, conflict_report, db, manifest as manifest_mod, markers, resolver
from helpip_cli._vendored.req import parse_req
from helpip_cli._vendored.semver import Version
from helpip_cli.parsing import Entry
from helpip_cli.storage import Storage


def _extract_lower_bound(spec: str) -> Optional[tuple[str, bool]]:
    """Return ``(version, is_strict_greater)`` for the lower bound, or None.

    Mirrors the JS ``_extractLowerBoundVersion``: ``==``/``>=`` are inclusive,
    ``>`` is strict; the highest such lower bound wins.
    """
    try:
        req = parse_req(spec)
    except Exception:
        return None
    if not req.specs:
        return None
    min_version: Optional[str] = None
    is_strict = False
    for op, version in req.specs:
        if op in ("==", ">="):
            if min_version is None or Version.parse(version) > Version.parse(min_version):
                min_version = version
                is_strict = False
        elif op == ">":
            if min_version is None or Version.parse(version) > Version.parse(min_version):
                min_version = version
                is_strict = True
            elif Version.parse(version) == Version.parse(min_version):
                is_strict = True
    if min_version is None:
        return None
    return min_version, is_strict


def _check_versions_before_pubgrub(
    ai_entries: list[Entry], manifest: Optional[dict], has_line_index: bool
) -> tuple[list[Entry], list[conflict_report.WarningItem]]:
    """Warn + splice out AI packages whose lower bound exceeds the manifest max."""
    warnings: list[conflict_report.WarningItem] = []
    kept: list[Entry] = []
    for entry in ai_entries:
        if not entry.has_version_constraint:
            kept.append(entry)
            continue
        max_version = manifest_mod.get_max_version(manifest, entry.package_name)
        if max_version is None:
            # Not in manifest packages map: skip (kept) — matches JS "continue".
            kept.append(entry)
            continue
        # null max version in manifest -> splice out (matches JS).
        if max_version == "" or max_version is None:
            continue
        lower = _extract_lower_bound(entry.spec)
        if lower is None:
            kept.append(entry)
            continue
        lower_version, is_strict = lower
        lower_v = Version.parse(lower_version)
        max_v = Version.parse(max_version)
        exceeds = (lower_v > max_v) or (lower_v == max_v and is_strict)
        if exceeds:
            warnings.append(
                conflict_report.WarningItem(
                    package_name=entry.package_name,
                    message='"{} {}" is newer than the latest known version ({}). '
                    "The dataset may need an update.".format(
                        entry.package_name, lower_version, max_version
                    ),
                    line_index=entry.line_index if has_line_index else None,
                )
            )
            continue
        kept.append(entry)
    return kept, warnings


def _load_dataset(path: Path) -> dict:
    with open(path, "r", encoding="utf-8") as fh:
        return json.load(fh)


@dataclass
class CheckOutcome:
    report: conflict_report.ConflictReport
    ai_package_names: list[str]


def run_conflict_check(
    entries: list[Entry], storage: Storage, *, has_line_index: bool
) -> CheckOutcome:
    """Run the full AI conflict-detection flow on parsed entries."""
    report = conflict_report.ConflictReport()
    package_db = db.PackageDb(storage)

    # 1. DB existence filter (exact-case).
    for entry in entries:
        entry.found = package_db.package_exists(entry.db_kind, entry.package_name)

    # 2. AI filter.
    manifest = manifest_mod.load(storage.path(config.MANIFEST_FILE))
    ai_entries = [
        e for e in entries if e.found and manifest_mod.is_ai_package(manifest, e.package_name)
    ]
    ai_package_names = [e.package_name for e in ai_entries]

    # 3. version-before-pubgrub (warn + splice, no network).
    ai_entries, warnings = _check_versions_before_pubgrub(ai_entries, manifest, has_line_index)
    report.warnings.extend(warnings)

    if not ai_entries:
        package_db.close()
        return CheckOutcome(report=report, ai_package_names=ai_package_names)

    # 4. Load + resolve.
    try:
        dataset = _load_dataset(storage.path(config.DATASET_FILE))
    except (OSError, ValueError) as exc:
        report.conflicts.append(
            conflict_report.ConflictItem(
                package_name=None,
                message="Could not load dependencies.json: {}".format(exc),
            )
        )
        package_db.close()
        return CheckOutcome(report=report, ai_package_names=ai_package_names)

    marker_env = markers.build_env()
    result = resolver.resolve(ai_entries, dataset, marker_env)
    conflicts, _ = conflict_report.build(result, ai_entries, has_line_index=has_line_index)
    report.conflicts.extend(conflicts)

    package_db.close()
    return CheckOutcome(report=report, ai_package_names=ai_package_names)
