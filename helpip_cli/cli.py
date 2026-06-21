# SPDX-License-Identifier: MIT
"""helpip command-line interface."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

from helpip_cli import config, diagnostics, download, manifest as manifest_mod, parsing
from helpip_cli.storage import NotInitializedError, Storage

# Exit codes.
EXIT_OK = 0
EXIT_CONFLICT = 1
EXIT_ERROR = 2

MANUAL = """\
helpip — AI dependency conflict detection

Detects AI-package dependency conflicts for a set of Python requirements using a
PubGrub solver over a local AI dependency dataset.

USAGE
  helpip init                       Initialize data sources in ~/.helpip/storage
  helpip -r <filepath>              Parse a dependency file and run the conflict check
  helpip -i <spec> [<spec> ...]     pip-install-style specs to check
  helpip update                     Check whether a dataset update is available
  helpip upgrade                    Re-fetch all data sources
  helpip -h                         Show this manual

DATA SOURCES (stored in $HOME/.helpip/storage)
  pypi.db, conda.db                 SQLite package-name databases (existence filter)
  dependencies.json                 Indexed AI dependency metadata (PubGrub input)
  dependencies_metadata.json        AI package list + max versions + schema version

  All four are downloaded from the GitHub/Gitee repo
  Sanpayon/PyPI_AI_Essential_Dependencies (Gitee mirror preferred for zh-CN locales).

SUPPORTED FILES (-r)
  requirements.txt                  one requirement per line
  pyproject.toml                    [project].dependencies (PEP 621) only
  environment.yml / environment.yaml  conda deps + pip: subsection

EXIT CODES
  0 no conflict (warnings may still be printed)
  1 one or more conflicts detected
  2 operational error (not initialized, parse/download failure)
"""


def _print_storage_summary(storage: Storage) -> None:
    print("helpip data at: {}".format(storage.root))
    manifest = manifest_mod.load(storage.path(config.MANIFEST_FILE))
    if manifest is not None:
        print("  manifest version: {}".format(manifest_mod.version(manifest) or "?"))
        print("  manifest updated: {}".format(manifest_mod.last_updated(manifest) or "?"))
        print("  AI packages known: {}".format(len(manifest.get("packages", {}))))
    for name in config.REQUIRED_FILES:
        mark = "ok" if storage.exists(name) else "MISSING"
        print("  [{}] {}".format(mark, name))


def cmd_init(storage: Storage, args) -> int:
    try:
        download.init_all(storage)
    except Exception as exc:  # noqa: BLE001
        print("error: initialization failed: {}".format(exc), file=sys.stderr)
        print("hint: check network connectivity; DBs must be published to the "
              "remote repo. Run `helpip upgrade` when available.", file=sys.stderr)
        return EXIT_ERROR
    _print_storage_summary(storage)
    print("Initialized helpip.")
    return EXIT_OK


def cmd_upgrade(storage: Storage, args) -> int:
    try:
        download.upgrade_all(storage)
    except Exception as exc:  # noqa: BLE001
        print("error: upgrade failed: {}".format(exc), file=sys.stderr)
        return EXIT_ERROR
    _print_storage_summary(storage)
    print("Upgraded helpip data.")
    return EXIT_OK


def cmd_update(storage: Storage, args) -> int:
    local_path = storage.path(config.MANIFEST_FILE)
    local = manifest_mod.load(local_path)
    if local is None:
        print("error: no local manifest found. Run `helpip init` first.", file=sys.stderr)
        return EXIT_ERROR
    local_ver = manifest_mod.version(local)
    session = download._session()
    remote = download.fetch_remote_manifest(session)
    if remote is None:
        print("error: could not fetch remote manifest. Check network and retry.",
              file=sys.stderr)
        return EXIT_ERROR
    remote_ver = manifest_mod.version(remote)
    if local_ver == remote_ver:
        print("Dataset is up to date (version {}).".format(local_ver))
    else:
        print("A dataset update is available: local {} -> remote {}.".format(
            local_ver, remote_ver))
        print("Run `helpip upgrade` to apply.")
    return EXIT_OK


def _print_report(outcome: diagnostics.CheckOutcome, *, has_line_index: bool) -> int:
    report = outcome.report
    for w in report.warnings:
        where = " (line {})".format(w.line_index + 1) if has_line_index and w.line_index is not None else ""
        print("warning: {}{}".format(w.message, where))
    if not report.has_conflict:
        if outcome.ai_package_names:
            print("AI packages checked: {}".format(", ".join(outcome.ai_package_names)))
        print("No AI dependency conflicts detected.")
        return EXIT_OK
    for c in report.conflicts:
        where = " (line {})".format(c.line_index + 1) if has_line_index and c.line_index is not None else ""
        if c.package_name:
            print("conflict: {}{}".format(c.package_name, where))
        else:
            print("conflict:{}".format(where))
        for line in c.message.splitlines() or ["version solving failed"]:
            print("    {}".format(line))
    return EXIT_CONFLICT


def cmd_run_file(storage: Storage, args) -> int:
    try:
        storage.require_initialized()
    except NotInitializedError as exc:
        print("error: {}".format(exc), file=sys.stderr)
        return EXIT_ERROR
    path = Path(args.run_file)
    if not path.exists():
        print("error: file not found: {}".format(path), file=sys.stderr)
        return EXIT_ERROR
    try:
        entries = parsing.parse_file(path)
    except ValueError as exc:
        print("error: {}".format(exc), file=sys.stderr)
        return EXIT_ERROR
    outcome = diagnostics.run_conflict_check(entries, storage, has_line_index=True)
    return _print_report(outcome, has_line_index=True)


def cmd_install(storage: Storage, args) -> int:
    try:
        storage.require_initialized()
    except NotInitializedError as exc:
        print("error: {}".format(exc), file=sys.stderr)
        return EXIT_ERROR
    entries = parsing.parse_cli_specs(args.install_specs)
    if not entries:
        print("error: no valid package specs provided.", file=sys.stderr)
        return EXIT_ERROR
    outcome = diagnostics.run_conflict_check(entries, storage, has_line_index=False)
    return _print_report(outcome, has_line_index=False)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="helpip",
        description="AI dependency conflict detection (PubGrub-based).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=MANUAL,
        add_help=True,
    )
    parser.add_argument(
        "-r", dest="run_file", metavar="FILEPATH",
        help="parse FILEPATH (requirements.txt/pyproject.toml/environment.yml) and run the AI conflict check",
    )
    parser.add_argument(
        "-i", dest="install_specs", metavar="SPEC", nargs="+",
        help="pip-install-style package specs (e.g. 'torch>=2.0') to check",
    )
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("init", help="initialize all data sources into ~/.helpip/storage")
    sub.add_parser("update", help="check whether a dataset update is available (notify only)")
    sub.add_parser("upgrade", help="re-fetch all data sources into ~/.helpip/storage")
    return parser


_SUBCOMMANDS = ("init", "update", "upgrade")


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    argv = list(sys.argv[1:]) if argv is None else list(argv)

    # Detect subcommand vs -r/-i on the raw argv, because -i (nargs="+")
    # would otherwise swallow a trailing subcommand as a package spec.
    has_flag = "-r" in argv or "-i" in argv
    subcommand_present = any(tok in _SUBCOMMANDS for tok in argv)
    if has_flag and subcommand_present:
        parser.error("use either -r/-i or a subcommand (init/update/upgrade), not both")

    args = parser.parse_args(argv)

    storage = Storage()

    if args.run_file:
        return cmd_run_file(storage, args)
    if args.install_specs:
        return cmd_install(storage, args)
    if args.command == "init":
        return cmd_init(storage, args)
    if args.command == "update":
        return cmd_update(storage, args)
    if args.command == "upgrade":
        return cmd_upgrade(storage, args)

    # No command/flag: print the manual (like -h).
    parser.print_help()
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
