# SPDX-License-Identifier: BSD-3-Clause
"""Vendored PubGrub engine (mixology) and semver, taken from pipgrip (BSD-3-Clause).

These are copied verbatim from pipgrip's ``libs/mixology`` and ``libs/semver``,
with pip/pkg_resources dependencies stripped out (see ``req.py``). They provide
the conflict-driven PubGrub version solver and the human-readable
``SolverFailure`` conflict report used by ``helpip``.
"""
