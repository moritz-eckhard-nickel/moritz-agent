# SPDX-License-Identifier: LicenseRef-MSOL-1.1
"""The tests never see the local configuration of the machine they run on.

On Sophie-1 the test scripts write config/moritz-agent.toml (for example the measured --moecpu) and
the model cache holds a real model – the tests must still see the defaults of the example file.
"""

from __future__ import annotations

import os

os.environ["MORITZ_TESTS_IGNORE_LOCAL_CONFIG"] = "1"
