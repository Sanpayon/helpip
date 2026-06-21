# SPDX-License-Identifier: MIT
"""Parse dependency specs from requirements.txt, pyproject.toml, environment.yml.

Faithful to ``vscode-extension/lsp/diagnostics.js``:
- requirements.txt: line-by-line, skip blank/``#``, spec = whole line, pypi.
- pyproject.toml: read ONLY ``[project].dependencies`` (PEP 621), pypi.
- environment.yml: str deps -> conda; ``{pip: [...]}`` -> pypi.

The ``-i`` CLI specs are parsed like pip-install arguments (pypi, no line index).
"""
from __future__ import annotations

import re
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, Optional

import yaml

DbKind = Literal["pypi", "conda"]

_NAME_RE = re.compile(r"^([a-zA-Z0-9_\-\.+]+)")
# package_name [extras] <remainder>; used to detect whether a constraint follows.
_HAS_CONSTRAINT_RE = re.compile(r"^([A-Za-z0-9][A-Za-z0-9._+-]*)(?:\[[^\]]*\])?\s*(.*)$")


@dataclass
class Entry:
    package_name: str
    spec: str
    line_index: int = -1
    has_version_constraint: bool = False
    db_kind: DbKind = "pypi"
    found: bool = False


def extract_package_name(spec: str) -> Optional[str]:
    if not spec or not isinstance(spec, str):
        return None
    m = _NAME_RE.match(spec)
    return m.group(1) if m else None


def has_version_constraint(spec: str) -> bool:
    if not spec or not isinstance(spec, str):
        return False
    # Drop environment markers (everything after ';') before checking.
    requirement = spec.split(";", 1)[0].strip()
    m = _HAS_CONSTRAINT_RE.match(requirement)
    if not m:
        return False
    return bool(m.group(2).strip())


def _entry(spec: str, line_index: int, db_kind: DbKind) -> Optional[Entry]:
    name = extract_package_name(spec)
    if not name:
        return None
    return Entry(
        package_name=name,
        spec=spec,
        line_index=line_index,
        has_version_constraint=has_version_constraint(spec),
        db_kind=db_kind,
    )


def parse_requirements(content: str) -> list[Entry]:
    entries: list[Entry] = []
    for i, raw in enumerate(content.split("\n")):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        entry = _entry(line, i, "pypi")
        if entry:
            entries.append(entry)
    return entries


def parse_pyproject(content: bytes) -> list[Entry]:
    entries: list[Entry] = []
    try:
        data = tomllib.loads(content.decode("utf-8") if isinstance(content, bytes) else content)
    except Exception:
        return entries
    project = data.get("project") if isinstance(data, dict) else None
    if not isinstance(project, dict):
        return entries
    deps = project.get("dependencies")
    if isinstance(deps, list):
        dep_list = deps
    elif isinstance(deps, dict):
        dep_list = list(deps.keys())
    else:
        return entries
    for dep in dep_list:
        if not isinstance(dep, str):
            continue
        entry = _entry(dep, -1, "pypi")
        if entry:
            entries.append(entry)
    return entries


def parse_environment(content: str) -> list[Entry]:
    """Parse environment.yml, returning conda + pip entries in source order."""
    entries: list[Entry] = []
    try:
        env = yaml.safe_load(content)
    except Exception:
        return entries
    if not isinstance(env, dict):
        return entries
    deps = env.get("dependencies")
    if not isinstance(deps, list):
        return entries
    for dep in deps:
        if isinstance(dep, str):
            entry = _entry(dep, -1, "conda")
            if entry:
                entries.append(entry)
        elif isinstance(dep, dict) and isinstance(dep.get("pip"), list):
            for pip_dep in dep["pip"]:
                if not isinstance(pip_dep, str):
                    continue
                entry = _entry(pip_dep, -1, "pypi")
                if entry:
                    entries.append(entry)
    return entries


def parse_cli_specs(specs: list[str]) -> list[Entry]:
    entries: list[Entry] = []
    for spec in specs:
        entry = _entry(spec, -1, "pypi")
        if entry:
            entries.append(entry)
    return entries


def detect_file_type(filename: str) -> Optional[Literal["requirements", "pyproject", "environment"]]:
    name = Path(filename).name
    if name == "requirements.txt" or (name.endswith(".txt") and "environment" not in name):
        return "requirements"
    if name == "pyproject.toml":
        return "pyproject"
    if name in ("environment.yml", "environment.yaml") or name.endswith((".yml", ".yaml")) and "environment" in name:
        return "environment"
    return None


def parse_file(path: Path) -> list[Entry]:
    ftype = detect_file_type(path.name)
    if ftype is None:
        raise ValueError(
            "Unrecognized dependency file: {} (expected requirements.txt, "
            "pyproject.toml, or environment.yml/.yaml)".format(path.name)
        )
    if ftype == "pyproject":
        with open(path, "rb") as fh:
            return parse_pyproject(fh.read())
    with open(path, "r", encoding="utf-8") as fh:
        content = fh.read()
    if ftype == "requirements":
        return parse_requirements(content)
    return parse_environment(content)
