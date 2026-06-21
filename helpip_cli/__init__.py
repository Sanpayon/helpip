# SPDX-License-Identifier: MIT
"""helpip — AI dependency conflict detection CLI.

Only the AI dependency conflict detection feature of the pip-helper VSCode
extension is ported here: parse a dependency file (or ``-i`` specs), keep the
AI packages, and run a PubGrub solver over a local ``dependencies.json`` to
report conflicts. The PubGrub engine is vendored from pipgrip (BSD-3-Clause)
under :mod:`helpip_cli._vendored`.
"""

__version__ = "0.1.0"
