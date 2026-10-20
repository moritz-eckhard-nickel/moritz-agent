# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Access to the shipped data files under assets/data/."""

from __future__ import annotations

import tomllib
from functools import cache
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parents[2] / "assets" / "data"


@cache
def load_toml(relative: str) -> dict[str, Any]:
    """Read ``assets/data/<relative>`` (TOML)."""
    return tomllib.loads((DATA_DIR / relative).read_text(encoding="utf-8"))


def data_path(relative: str) -> Path:
    return DATA_DIR / relative
