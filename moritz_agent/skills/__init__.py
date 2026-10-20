# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""Instant answers without the language model (docs/plan/13-sofortauskuenfte.md, ADR-029).

Time, calendar, weather for the home town (35781 Weilburg) or any spoken place, warnings, pollen,
sun and moon, calculations and many small helpers. Every answer comes from the system clock, a
calculation, a shipped data file or a data service – never from a language model.
"""

from __future__ import annotations
