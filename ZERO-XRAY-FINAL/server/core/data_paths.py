"""Stable persistent data locations for ZERO X-RAY.

The project is often distributed as a new ZIP/folder for each demo build.
Keeping runtime data inside ``server/data`` makes each extracted copy look
empty.  These helpers keep the live SQLite database and tenant uploads in a
stable folder outside the source tree, while still allowing explicit env
configuration for production/testing.
"""

from __future__ import annotations

import os
import shutil
from pathlib import Path


def _default_data_root() -> Path:
    configured = os.getenv("ZX_DATA_ROOT")
    if configured:
        return Path(configured).expanduser()

    # The user's demo environment is Windows and the project itself lives on D:.
    # Prefer a stable D:\ZERO-XRAY-DATA folder when D: exists.  On other
    # machines fall back to the user's home folder.
    if os.name == "nt" and Path("D:/").exists():
        return Path("D:/ZERO-XRAY-DATA")
    return Path.home() / "ZERO-XRAY-DATA"


def get_data_root() -> Path:
    root = _default_data_root()
    root.mkdir(parents=True, exist_ok=True)
    return root


def get_database_path(packaged_database: Path | None = None) -> Path:
    explicit = os.getenv("ZX_DATABASE_PATH")
    target = Path(explicit).expanduser() if explicit else get_data_root() / "runtime.db"
    target.parent.mkdir(parents=True, exist_ok=True)

    # First run after upgrading from an older ZIP: copy the packaged demo DB
    # once so existing demo accounts/data are not lost.  Never overwrite an
    # already-existing persistent DB.
    if not target.exists() and packaged_database and packaged_database.exists():
        shutil.copy2(packaged_database, target)

    return target


def get_tenant_files_root() -> Path:
    root = get_data_root() / "tenant_files"
    root.mkdir(parents=True, exist_ok=True)
    return root


def get_database_view_root() -> Path:
    root = get_data_root() / "database_view"
    root.mkdir(parents=True, exist_ok=True)
    return root
