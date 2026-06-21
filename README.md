# helpip

**AI dependency conflict detection for Python projects.**

`helpip` is a command-line tool that parses a dependency file (or a list of
`pip install`-style specs), keeps only the **AI-related packages**, and runs a
[PubGrub](https://medium.com/@nex3/pubgrub-2fb6470504f) version solver over a
local AI dependency dataset to report version conflicts — with a human-readable
explanation of *why* the conflict occurred and which packages/versions are
involved.

It is a Python rewrite of the AI conflict-detection feature of the
`pip-helper` VSCode extension, kept as a standalone, dependency-light CLI. No
run feature, no completion feature — only conflict detection.

## Installation

```bash
pip install helpip
```

Requires Python ≥ 3.11. Runtime dependencies: `packaging`, `pyyaml`, `requests`
(installed automatically).

## Quick start

```bash
# 1. Download the data sources (SQLite package DBs + AI dependency dataset)
helpip init

# 2. Check a dependency file for AI conflicts
helpip -r requirements.txt
helpip -r pyproject.toml
helpip -r environment.yml

# 3. Or check ad-hoc specs, pip-install style
helpip -i 'transformers==5.2.0' 'vllm==0.17.0'

# 4. Keep the dataset fresh
helpip update      # notify only: is a newer dataset available?
helpip upgrade     # re-download all data sources

# Manual
helpip -h
```

### Example output

```
$ helpip -i 'transformers==5.2.0' 'vllm==0.17.0'
conflict:
    Because vllm (0.17.0) depends on transformers (<5,>=4.56.0)
     and root depends on transformers (==5.2.0), vllm is forbidden.
    So, because root depends on vllm (==0.17.0), version solving failed.
```

The solver explains the conflict in plain PubGrub terms: which package requires
which version range, and how it collides with your top-level pins.

## Commands

| Command | Description |
| --- | --- |
| `helpip init` | Initialize all data sources into `~/.helpip/storage`. |
| `helpip -r <file>` | Parse a dependency file and run the AI conflict check. |
| `helpip -i <spec> [<spec>...]` | Check `pip install`-style package specs. |
| `helpip update` | Fetch the remote manifest and report whether an update is available (notify only). |
| `helpip upgrade` | Re-fetch all data sources. |
| `helpip -h` | Show the manual. |

**Exit codes:** `0` no conflict (warnings may still print) · `1` conflict(s)
detected · `2` operational error (not initialized / parse / download failure).

## Supported dependency files (`-r`)

- **`requirements.txt`** — one requirement per line; blank lines and `#`
  comments skipped.
- **`pyproject.toml`** — `[project].dependencies` (PEP 621) only. `[tool.poetry]`,
  `[tool.pdm]`, and optional-dependencies are not read.
- **`environment.yml` / `environment.yaml`** — the `dependencies:` list; string
  items are conda deps, `{pip: [...]}` subsections are pip deps.

Version constraint operators supported: `>=`, `>`, `<=`, `<`, `==`, `!=`, `~=`
(compatible release), `==X.*` / `!=X.*` wildcards. PEP 508 environment markers
are evaluated against the current interpreter.

## Data sources

`helpip` stores four files in `$HOME/.helpip/storage/` (Linux `~`, Windows
`C:/Users/username`; override with the `HELPIP_HOME` environment variable):

| File | Purpose |
| --- | --- |
| `pypi.db`, `conda.db` | SQLite package-name databases, used as an exact-case existence filter. |
| `dependencies.json` | Indexed AI dependency metadata; the PubGrub solver input. |
| `dependencies_metadata.json` | AI package list + max known versions + schema version. |

All four are downloaded from the
`Sanpayon/PyPI_AI_Essential_Dependencies` GitHub/Gitee repository, with mirror
failover (the Gitee mirror is preferred for zh-CN locales). `init` and `upgrade`
download all four; `update` only compares the remote manifest version and
notifies — it does not modify local data.

A package is treated as an **AI package** if and only if its lowercased name is a
key in `dependencies_metadata.json`'s `packages` map. Only AI packages are passed
to the solver.

## How it works

1. Parse the file / specs into `(package, version_constraint)` entries.
2. Keep entries whose package name exists in `pypi.db`/`conda.db` (exact-case).
3. Keep entries that are AI packages per the manifest.
4. **Pre-check:** if an entry's lower bound exceeds the manifest's max known
   version, emit a "newer than latest known — the dataset may need an update"
   warning and drop it from the solve.
5. Run the PubGrub solver over `dependencies.json` for the remaining AI specs.
6. On conflict, print the solver's multi-line explanation.

The PubGrub engine is vendored (BSD-3-Clause, from
[`pipgrip`](https://github.com/ddelange/pipgrip)'s `libs/mixology` and
`libs/semver`) under `helpip_cli._vendored`, with its pip dependency replaced by
`packaging`. This makes `helpip` self-contained — no pip, no network at solve
time, no external PubGrub package required.

## Limitations

- Extras requested at the root (e.g. `helpip -i 'dep[docs]==1.0'`) are not
  fully modeled; extra-gated transitive dependencies are dropped.
- The marker environment reflects the *current* interpreter, not a target venv.
- The solver is complete (conflict-driven PubGrub); conflict attribution may
  differ from a naive first-conflict backtracker, but is more precise.

## License

MIT. The vendored PubGrub engine (`helpip_cli._vendored/mixology` and
`helpip_cli/_vendored/semver`) is BSD-3-Clause, © pipgrip authors.
