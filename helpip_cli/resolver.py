# SPDX-License-Identifier: MIT
"""PubGrub resolver bridge over the indexed ``dependencies.json``.

We vendor pipgrip's mixology engine (see :mod:`helpip_cli._vendored.mixology`)
and implement a :class:`DependenciesPackageSource` that reads the indexed
dataset instead of fetching PyPI wheels. On conflict, the engine's
``SolverFailure.__str__`` yields a multi-line human-readable explanation.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any, Optional

from helpip_cli._vendored.mixology.constraint import Constraint
from helpip_cli._vendored.mixology.failure import SolverFailure
from helpip_cli._vendored.mixology.package import Package
from helpip_cli._vendored.mixology.package_source import PackageSource as BasePackageSource
from helpip_cli._vendored.mixology.range import EmptyRange, Range
from helpip_cli._vendored.mixology.union import Union
from helpip_cli._vendored.mixology.version_solver import VersionSolver
from helpip_cli._vendored.req import ParsedRequirement, parse_req
from helpip_cli._vendored.semver import (
    EmptyConstraint,
    Version,
    VersionRange,
    VersionUnion,
    parse_constraint,
)
from helpip_cli import markers

# For non-base packages without a version constraint, the solver only sees the
# single newest version.  Exploring older releases is rarely useful — a user
# who needs an old version should pin it explicitly — and the PubGrub search
# space explodes combinatorially when dozens of unconstrained packages are in
# the root set.  (Bump this to 3-5 if you need limited backtracking.)
_UNCONSTRAINED_WINDOW = 1


class InvalidDatasetError(ValueError):
    pass


class Dependency:
    """A dependency returned by ``dependencies_for``."""

    def __init__(self, name: str, constraint_str: str, pip_string: str) -> None:
        self.name = name
        self.constraint = _cached_parse_constraint(constraint_str or "*")
        self.pretty_constraint = constraint_str or "*"
        self.pip_string = pip_string
        self.package = Package(pip_string)

    def __str__(self) -> str:
        return self.pretty_constraint

    def __repr__(self) -> str:
        return "Dependency({}, {})".format(self.pip_string, self.pretty_constraint)


def _specs_to_constraint(specs) -> str:
    """``[(op, version), ...]`` -> a comma-joined constraint string."""
    return ",".join("{}{}".format(op, version) for op, version in specs)


@lru_cache(maxsize=32768)
def _cached_parse_constraint(constraint_str: str):
    return parse_constraint(constraint_str)


def _constraint_key(constraint) -> Optional[tuple]:
    """Hashable key for ``_versions_for`` filter cache."""
    if constraint is None:
        return None
    t = type(constraint).__name__
    if t == "Range":
        return ("Range", constraint.min, constraint.max,
                constraint.include_min, constraint.include_max)
    if t == "Union":
        inner = tuple(
            (r.min, r.max, r.include_min, r.include_max)
            for r in sorted(constraint.ranges,
                            key=lambda r: (str(r.min) if r.min else "", str(r.max) if r.max else ""))
        )
        return ("Union", inner)
    if t == "EmptyRange":
        return ("EmptyRange",)
    return ("other",)


class DependenciesPackageSource(BasePackageSource):
    """PackageSource backed by the indexed ``dependencies.json`` dataset.

    *Version* objects are pre-parsed at init time (cheap, ~632K calls).
    *Dependency* objects are built lazily on the solver's first visit to a
    (package, version) pair and then cached — this avoids parsing 7.9M
    requirement edges for packages the solver never reaches.
    """

    def __init__(self, dataset: dict, marker_env: Optional[dict] = None) -> None:
        if not isinstance(dataset, dict):
            raise InvalidDatasetError("dataset must be an object")
        packages = dataset.get("packages")
        requirement_index = dataset.get("requirement_index")
        if not isinstance(packages, dict):
            raise InvalidDatasetError('dataset "packages" must be an object')
        if requirement_index is not None and not isinstance(requirement_index, list):
            raise InvalidDatasetError('dataset "requirement_index" must be an array')
        self._requirement_index: list[str] = list(requirement_index or [])

        # canonical_name -> sorted list[Version] (newest-first)
        self._versions_list: dict[str, list[Version]] = {}
        # canonical_name -> {version_str -> list[str]} (raw req strings, resolved)
        self._requires_raw: dict[str, dict[str, list[str]]] = {}
        # canonical names whose EVERY version has zero dependencies (leaf packages).
        self._base_packages: set[str] = set()

        for name, record in packages.items():
            if not isinstance(record, dict):
                continue
            versions = record.get("versions")
            if not isinstance(versions, dict):
                continue
            canonical = parse_req(name).key
            vers: dict[str, list[str]] = {}
            version_objs: list[Version] = []
            all_leaf = True
            for ver, ver_record in versions.items():
                if not isinstance(ver_record, dict):
                    continue
                requires = ver_record.get("requires")
                if requires is None:
                    resolved: list[str] = []
                elif isinstance(requires, list):
                    resolved = self._resolve_requires(requires)
                else:
                    continue
                vers[ver] = resolved
                version_objs.append(Version.parse(ver))
                if resolved:
                    all_leaf = False
            if vers:
                self._versions_list[canonical] = sorted(version_objs, reverse=True)
                self._requires_raw[canonical] = vers
                if all_leaf:
                    self._base_packages.add(canonical)

        # Lazy caches — populated on first solver access, live for one solve
        self._deps_cache: dict[tuple, list[Dependency]] = {}
        self._filter_cache: dict[tuple, list[Version]] = {}

        self._marker_env = marker_env
        self._root_dependencies: list[Dependency] = []
        self._root_version = Version.parse("0.0.0")
        super().__init__()

    def _resolve_requires(self, requires: list) -> list[str]:
        """Resolve a ``requires`` list to requirement strings.

        Supports int-indexed (via ``requirement_index``) and direct-string entries.
        """
        out: list[str] = []
        for entry in requires:
            if isinstance(entry, str):
                out.append(entry)
            elif isinstance(entry, int) and 0 <= entry < len(self._requirement_index):
                out.append(self._requirement_index[entry])
        return out

    def _build_deps(self, pkg_name: str, ver_str: str) -> list[Dependency]:
        """Build the cached ``Dependency`` list for one (package, version)."""
        raw = self._requires_raw.get(pkg_name, {}).get(ver_str)
        if not raw:
            return []
        deps: list[Dependency] = []
        for req_str in raw:
            if not markers.should_include(req_str, self._marker_env):
                continue
            try:
                req = parse_req(req_str)
            except Exception:
                continue
            if req.url:
                continue
            constraint = _specs_to_constraint(req.specs)
            deps.append(Dependency(req.key, constraint, str(req)))
        return deps

    # -- BasePackageSource contract -----------------------------------------

    @property
    def root_version(self):
        return self._root_version

    def root_dep(self, pip_string: str) -> None:
        req = parse_req(pip_string)
        constraint = req.url or _specs_to_constraint(req.specs)
        self._root_dependencies.append(Dependency(req.key, constraint, str(req)))

    def _versions_for(self, package, constraint=None) -> list:
        versions = self._versions_list.get(package.name)
        if not versions:
            return []

        # Unconstrained selection: trim candidate count to keep backtracking
        # tractable.  Base (leaf) packages get exactly 1 — no reason to try
        # older releases of a package that has no transitive dependencies.
        # Non-base packages get a small window of the newest versions.
        if constraint is None:
            if package.name in self._base_packages:
                return versions[:1]
            if len(versions) > _UNCONSTRAINED_WINDOW:
                return versions[:_UNCONSTRAINED_WINDOW]
            return versions

        ckey = _constraint_key(constraint)
        if ckey is not None:
            cache_key = (package.name, ckey)
            cached = self._filter_cache.get(cache_key)
            if cached is not None:
                return cached

        out = []
        for version in versions:
            point = Range(version, version, True, True)
            if constraint.allows_any(point):
                out.append(version)

        # Also prune constrained-but-huge result sets (e.g. `package>=0.1` on
        # a package with 2000 versions — the solver can't try them all anyway).
        if len(out) > _UNCONSTRAINED_WINDOW:
            out = out[:_UNCONSTRAINED_WINDOW]

        if ckey is not None:
            self._filter_cache[(package.name, ckey)] = out
        return out

    def dependencies_for(self, package, version) -> list:
        if package == self.root:
            return self._root_dependencies
        cache_key = (package.name, str(version))
        cached = self._deps_cache.get(cache_key)
        if cached is not None:
            return cached
        deps = self._build_deps(package.name, str(version))
        self._deps_cache[cache_key] = deps
        return deps

    def convert_dependency(self, dependency: Dependency):
        constraint = dependency.constraint
        if isinstance(constraint, EmptyConstraint):
            mix_constraint = EmptyRange()
        elif isinstance(constraint, VersionRange):
            mix_constraint = Range(
                constraint.min,
                constraint.max,
                constraint.include_min,
                constraint.include_max,
                dependency.pretty_constraint,
            )
        else:
            ranges = [
                Range(
                    _r.min, _r.max, _r.include_min, _r.include_max, str(_r),
                )
                for _r in constraint.ranges
            ]
            mix_constraint = Union.of(*ranges)
        return Constraint(dependency.package, mix_constraint)


@dataclass
class ResolveResult:
    error: bool
    message: Optional[str] = None
    decisions: dict[str, str] = field(default_factory=dict)


def resolve(ai_specs, dataset: dict, marker_env: Optional[dict] = None) -> ResolveResult:
    """Run the PubGrub solver over the AI specs.

    ``ai_specs`` is an iterable of objects with a ``.spec`` attribute (the raw
    requirement string). Returns ``ResolveResult``; on conflict ``message`` is
    the engine's multi-line explanation.
    """
    source = DependenciesPackageSource(dataset, marker_env)
    for s in ai_specs:
        if markers.should_include(s.spec, marker_env):
            source.root_dep(s.spec)

    solver = VersionSolver(source, threads=1)
    try:
        # Cap iterations at 200 — enough for most real-world dependency
        # graphs (2-5 AI packages with pinned versions).  A larger graph
        # (12+ unconstrained packages) will hit this cap in ~13s and
        # report the unsatisfied packages with actionable guidance.
        result = solver.solve(max_steps=200)
    except SolverFailure as exc:
        msg = str(exc)
        # For step-limit failures, use the clear message we attached.
        if hasattr(exc, '_incompatibility') and hasattr(exc._incompatibility, '_step_limit_msg'):
            msg = exc._incompatibility._step_limit_msg
        return ResolveResult(error=True, message=msg)
    except Exception as exc:  # noqa: BLE001
        return ResolveResult(error=True, message="Resolution failed: {}".format(exc))

    decisions = {str(pkg): str(ver) for pkg, ver in result.decisions.items()}
    return ResolveResult(error=False, decisions=decisions)
