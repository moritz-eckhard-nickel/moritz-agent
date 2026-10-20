# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""The skills themselves, grouped as in docs/plan/13 §6 (importing a module registers its skills)."""

from __future__ import annotations

import importlib

_MODULES = (
    "zeit",
    "kalender",
    "rechnen",
    "helfer",
    "gespraech",
    "orte",
    "wetter",
    "warnungen",
    "ratschlaege",
    "himmel",
    "geld",
    "region",
)
_loaded = False


def load_all() -> None:
    global _loaded
    if _loaded:
        return
    _loaded = True
    for name in _MODULES:
        try:
            importlib.import_module(f"{__name__}.{name}")
        except ModuleNotFoundError as exc:  # modules arrive wave by wave
            if exc.name != f"{__name__}.{name}":
                raise
