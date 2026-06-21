# SPDX-License-Identifier: MIT
"""Remote download of helpip's four data sources with mirror failover."""
from __future__ import annotations

import io
import json
import shutil
import zipfile
from pathlib import Path
from typing import Callable, Iterable, Optional

import requests

from helpip_cli import config
from helpip_cli.storage import Storage


class DownloadError(RuntimeError):
    """Raised when a download fails on every mirror."""


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({"User-Agent": config.USER_AGENT})
    return s


def download_file(url: str, dest: Path, session: requests.Session) -> None:
    """Stream ``url`` to ``dest``. Raises on HTTP error; follows redirects."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".part")
    try:
        with session.get(url, stream=True, timeout=60) as resp:
            if resp.status_code != 200:
                raise DownloadError(
                    "HTTP {} for {}".format(resp.status_code, url)
                )
            with open(tmp, "wb") as fh:
                for chunk in resp.iter_content(chunk_size=1 << 16):
                    if chunk:
                        fh.write(chunk)
        tmp.replace(dest)
    except Exception:
        _remove(tmp)
        raise


def _remove(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


def _with_failover(
    url_map: dict, session: requests.Session, fn: Callable[[str], None], what: str
) -> None:
    last_error: Optional[Exception] = None
    for url in config.preferred_mirrors(url_map):
        try:
            fn(url)
            return
        except Exception as exc:  # noqa: BLE001 - any failure -> try next mirror
            last_error = exc
            _log("Failed to download {} from {}: {}".format(what, url, exc))
    raise DownloadError(
        "Could not download {} from any mirror: {}".format(what, last_error)
    )


def _log(message: str) -> None:
    # Lightweight; the CLI prints progress. Avoid importing logging lazily.
    import logging

    logging.getLogger("helpip").debug(message)


def download_manifest(storage: Storage, session: requests.Session) -> Path:
    dest = storage.path(config.MANIFEST_FILE)
    _with_failover(
        config.MANIFEST_URLS,
        session,
        lambda url: download_file(url, dest, session),
        config.MANIFEST_FILE,
    )
    return dest


def fetch_remote_manifest(session: requests.Session) -> Optional[dict]:
    """Fetch the remote manifest into memory (no storage write) for `update`."""
    last_error: Optional[Exception] = None
    for url in config.preferred_mirrors(config.MANIFEST_URLS):
        try:
            resp = session.get(url, timeout=30)
            if resp.status_code != 200:
                raise DownloadError("HTTP {} for {}".format(resp.status_code, url))
            return json.loads(resp.content.decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            last_error = exc
            _log("Failed to fetch remote manifest from {}: {}".format(url, exc))
    return None


def _find_recursive(root: Path, target: str) -> Optional[Path]:
    for entry in root.rglob(target):
        if entry.is_file():
            return entry
    return None


def download_dataset(storage: Storage, session: requests.Session) -> Path:
    """Download dependencies.zip, extract, and place dependencies.json in storage."""
    dest = storage.path(config.DATASET_FILE)
    zip_path = storage.path(config.ZIP_FILE)
    try:
        _with_failover(
            config.DATASET_ZIP_URLS,
            session,
            lambda url: download_file(url, zip_path, session),
            config.ZIP_FILE,
        )
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(storage.root)

        if dest.exists():
            return dest
        # The archive may nest dependencies.json in a subdirectory; flatten it.
        found = _find_recursive(storage.root, config.DATASET_FILE)
        if found is not None and found != dest:
            shutil.move(str(found), str(dest))
            # Clean up the empty wrapper directory the archive may have created.
            parent = found.parent
            while parent != storage.root and parent.exists():
                try:
                    parent.rmdir()
                except OSError:
                    break
                parent = parent.parent
        if not dest.exists():
            raise DownloadError(
                "Extracted archive did not produce {}".format(config.DATASET_FILE)
            )
        return dest
    finally:
        _remove(zip_path)
        _remove(dest.with_suffix(dest.suffix + ".part"))


def download_db(name: str, url_map: dict, storage: Storage, session: requests.Session) -> Path:
    dest = storage.path(name)
    _with_failover(
        url_map, session, lambda url: download_file(url, dest, session), name
    )
    return dest


def init_all(storage: Storage, session: requests.Session | None = None) -> None:
    """Download all four data sources into storage."""
    storage.ensure_dir()
    session = session or _session()
    download_db(config.PYPI_DB, config.PYPI_DB_URLS, storage, session)
    download_db(config.CONDA_DB, config.CONDA_DB_URLS, storage, session)
    download_dataset(storage, session)
    download_manifest(storage, session)


# `upgrade` is the same as `init`: re-download every source.
upgrade_all = init_all
