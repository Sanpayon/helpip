# SPDX-License-Identifier: MIT
"""PubGrub resolver bridge over the indexed ``dependencies.json``.

We vendor pipgrip's mixology engine (see :mod:`helpip_cli._vendored.mixology`)
and implement a :class:`DependenciesPackageSource` that reads the indexed
dataset instead of fetching PyPI wheels. On conflict, the engine's
``SolverFailure.__str__`` yields a multi-line human-readable explanation.
"""
from __future__ import annotations

from dataclasses import dataclass, field
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


class InvalidDatasetError(ValueError):
    pass


class Dependency:
    """A dependency returned by ``dependencies_for`` and converted via
    ``convert_dependency``. Mirrors pipgrip's Dependency but is pip-free."""

    def __init__(self, name: str, constraint_str: str, pip_string: str) -> None:
        self.name = name
        self.constraint = parse_constraint(constraint_str or "*")
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


class DependenciesPackageSource(BasePackageSource):
    """PackageSource backed by the indexed ``dependencies.json`` dataset.

    Dataset shape::

        {
          "version": "...",
          "requirement_index": ["torch>=2.0", "numpy>=1.20", ...],
          "packages": {
            "torch": {"versions": {"2.1.0": {"requires": [0, 1]}}}
          }
        }
    """

    def __init__(self, dataset: dict, marker_env: Optional[dict] = None) -> None:
        if not isinstance(dataset, dict):
            raise InvalidDatasetError("dataset must be an object")
        packages = dataset.get("packages")
        requirement_index = dataset.get("requirement_index")
        if not isinstance(packages, dict):
            raise InvalidDatasetError('dataset "packages" must be an object')
        # requirement_index is optional: the published dataset stores the
        # requirement strings directly in each version's "requires" list.
        if requirement_index is not None and not isinstance(requirement_index, list):
            raise InvalidDatasetError('dataset "requirement_index" must be an array')
        self._requirement_index: list[str] = list(requirement_index or [])

        # canonical_name -> {version_str -> list[req_str]}
        # Normalizes both the indexed form (requires: [int, ...]) and the
        # direct-string form (requires: ["pkg>=1.0", ...]) to a list of
        # requirement strings.
        self._versions: dict[str, dict[str, list[str]]] = {}
        for name, record in packages.items():
            if not isinstance(record, dict):
                continue
            versions = record.get("versions")
            if not isinstance(versions, dict):
                continue
            clean: dict[str, list[str]] = {}
            for ver, ver_record in versions.items():
                if not isinstance(ver_record, dict):
                    continue
                requires = ver_record.get("requires")
                # A missing/empty "requires" means the version has no
                # dependencies (a leaf package) — keep it with an empty list
                # rather than dropping it. Drop only malformed non-list values.
                if requires is None:
                    resolved: list[str] = []
                elif isinstance(requires, list):
                    resolved = self._resolve_requires(requires)
                else:
                    continue
                clean[ver] = resolved
            if clean:
                self._versions[parse_req(name).key] = clean

        self._marker_env = marker_env
        self._root_dependencies: list[Dependency] = []
        self._root_version = Version.parse("0.0.0")
        super().__init__()

    def _resolve_requires(self, requires: list) -> list[str]:
        """Convert a version's ``requires`` list to requirement strings.

        Supports both published formats:
        - direct strings: ``["numpy>=1.17", "packaging>=20.0"]``
        - integer indices into ``requirement_index``: ``[0, 1]``
        Mixed lists fall back to stringifying non-string entries via the index.
        """
        out: list[str] = []
        for entry in requires:
            if isinstance(entry, str):
                out.append(entry)
            elif isinstance(entry, int) and 0 <= entry < len(self._requirement_index):
                out.append(self._requirement_index[entry])
        return out

    # -- BasePackageSource contract -----------------------------------------

    @property
    def root_version(self):
        return self._root_version

    def root_dep(self, pip_string: str) -> None:
        req = parse_req(pip_string)
        constraint = req.url or _specs_to_constraint(req.specs)
        self._root_dependencies.append(Dependency(req.key, constraint, str(req)))

    def _versions_for(self, package, constraint=None) -> list:
        versions_map = self._versions.get(package.name)
        if not versions_map:
            return []
        out = []
        for ver_str in versions_map.keys():
            version = Version.parse(ver_str)
            point = Range(version, version, True, True)
            if constraint is None or constraint.allows_any(point):
                out.append(version)
        return sorted(out, reverse=True)

    def dependencies_for(self, package, version) -> list:
        if package == self.root:
            return self._root_dependencies
        versions_map = self._versions.get(package.name)
        if not versions_map:
            return []
        requires = versions_map.get(str(version))
        if not requires:
            return []
        deps: list[Dependency] = []
        for req_str in requires:
            if not markers.should_include(req_str, self._marker_env):
                continue
            try:
                req = parse_req(req_str)
            except Exception:
                continue
            if req.url:
                # Direct references are not supported in the dataset model.
                continue
            constraint = _specs_to_constraint(req.specs)
            deps.append(Dependency(req.key, constraint, str(req)))
        return deps

    def convert_dependency(self, dependency: Dependency):
        constraint = dependency.constraint
        if isinstance(constraint, EmptyConstraint):
            # An impossible (self-contradictory) requirement: nothing can satisfy it.
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
                    _r.min,
                    _r.max,
                    _r.include_min,
                    _r.include_max,
                    str(_r),
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
        result = solver.solve()
    except SolverFailure as exc:
        return ResolveResult(error=True, message=str(exc))
    except Exception as exc:  # noqa: BLE001
        return ResolveResult(error=True, message="Resolution failed: {}".format(exc))

    decisions = {str(pkg): str(ver) for pkg, ver in result.decisions.items()}
    return ResolveResult(error=False, decisions=decisions)
