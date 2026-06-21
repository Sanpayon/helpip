# SPDX-License-Identifier: MIT
"""Paths and remote source URLs for helpip."""
from __future__ import annotations

import os
import time
from pathlib import Path

# --- Storage ---------------------------------------------------------------

REPO_SLUG_GITHUB = "Sanpayon/PyPI_AI_Essential_Dependencies"
REPO_SLUG_GITEE = "Sanpayon/PyPI_AI_Essential_Dependencies"

PYPI_DB = "pypi.db"
CONDA_DB = "conda.db"
DATASET_FILE = "dependencies.json"
MANIFEST_FILE = "dependencies_metadata.json"
ZIP_FILE = "dependencies.zip"

# Files that must exist for the tool to be considered "initialized".
REQUIRED_FILES = (PYPI_DB, CONDA_DB, DATASET_FILE, MANIFEST_FILE)

USER_AGENT = "helpip/{}".format("0.1.0")


def storage_dir() -> Path:
    """``$HOME/.helpip/storage`` (overridable via ``HELPIP_HOME`` for tests).

    On Linux ``$HOME`` is ``~``; on Windows it resolves to
    ``C:/Users/username`` via :func:`pathlib.Path.home`.
    """
    home = os.environ.get("HELPIP_HOME")
    base = Path(home) if home else Path.home()
    return base / ".helpip" / "storage"


# --- Remote URLs -----------------------------------------------------------
# Mirror the JS extension's facts/dependency-dataset.js constants. The two .db
# files are published to the same raw repo as dependencies.zip (user-managed).

_GITHUB_ZIP = (
    "https://github.com/{}/raw/refs/heads/main/{}".format(REPO_SLUG_GITHUB, ZIP_FILE)
)
_GITEE_ZIP = "https://gitee.com/{}/raw/main/{}".format(REPO_SLUG_GITEE, ZIP_FILE)

_GITHUB_MANIFEST = (
    "https://raw.githubusercontent.com/{}/refs/heads/main/{}".format(
        REPO_SLUG_GITHUB, MANIFEST_FILE
    )
)
_GITEE_MANIFEST = (
    "https://raw.giteeusercontent.com/{}/raw/main/{}".format(
        REPO_SLUG_GITEE, MANIFEST_FILE
    )
)

_GITHUB_PYPI_DB = (
    "https://github.com/{}/raw/refs/heads/main/{}".format(REPO_SLUG_GITHUB, PYPI_DB)
)
_GITEE_PYPI_DB = "https://gitee.com/{}/raw/main/{}".format(REPO_SLUG_GITEE, PYPI_DB)

_GITHUB_CONDA_DB = (
    "https://github.com/{}/raw/refs/heads/main/{}".format(REPO_SLUG_GITHUB, CONDA_DB)
)
_GITEE_CONDA_DB = "https://gitee.com/{}/raw/main/{}".format(REPO_SLUG_GITEE, CONDA_DB)

# name -> {github, gitee} URL maps.
DATASET_ZIP_URLS = {"github": _GITHUB_ZIP, "gitee": _GITEE_ZIP}
MANIFEST_URLS = {"github": _GITHUB_MANIFEST, "gitee": _GITEE_MANIFEST}
PYPI_DB_URLS = {"github": _GITHUB_PYPI_DB, "gitee": _GITEE_PYPI_DB}
CONDA_DB_URLS = {"github": _GITHUB_CONDA_DB, "gitee": _GITEE_CONDA_DB}


def _prefer_gitee() -> bool:
    """Prefer the Gitee mirror for zh-CN locales or the Asia/Shanghai timezone."""
    lang = (
        os.environ.get("LANG", "") + " " + os.environ.get("LC_ALL", "")
        + " " + os.environ.get("LC_MESSAGES", "")
    ).lower()
    if "zh" in lang:
        return True
    # Best-effort tz detection without third-party libs.
    try:
        if "Asia/Shanghai" in (time.tzname + (time.localtime().tm_zone,)):
            return True
    except Exception:
        pass
    return False


def preferred_mirrors(url_map):
    """Return the mirror URLs in preferred order (Gitee-first when Chinese)."""
    if _prefer_gitee():
        return [url_map["gitee"], url_map["github"]]
    return [url_map["github"], url_map["gitee"]]
