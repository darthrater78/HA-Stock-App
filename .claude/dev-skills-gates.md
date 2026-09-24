# Dev Skills gate state
Track: release sequence (v2.7.15 shipped)
Mode: semi-autonomous (approved 2026-09-24) — commits and the tag still require the user's approval
Origin: darthrater78/HA-Stock-App (not a fork)
Standards: n/a — HA integration, no auth/Docker; at-rest: HA config entry storage (HA-managed); main-page links ✅
Version: 2.7.15
Updated: 2026-09-24

🔢 VERSION    ✅ all refs at 2.7.15, v2.7.14 tagged
    manifest.json 2.7.15; README top links repo + v2.7.15 release notes (added)
🔨 BUILD      ✅ CI-only + user check — HA runtime not installable here
    HA needs Python >=3.14.2, container has 3.11; compile, pyflakes,
    29 tests, actionlint all pass locally on a stable tree
    Owed before tag: user confirms 9:30 fetch on their HA from the PR branch
    Unproven release steps: "release" environment, gate empty-run retry
🔒 SECURITY   ✅ 0 open — 0 Critical, 0 High
    Pattern scan clean; pip-audit 2.10.1 clean on monarchmoneycommunity>=1.6.0
    Fixed: unused dt_time import (Low, pre-existing); workflow audit Lows
    Dependabot alerts setting: user to confirm (not queryable from here)
📄 DOCS       ✅ v2.7.15 entry; schedule diagram corrected (EOD 16:05, 9:30 fetch)
📦 RELEASE    ✅ commit approved 2026-09-24, release PR to master
🚀 SHIP       ✅ v2.7.15 tagged at 9c18db2, release published 2026-09-24
    First tag landed on 2c822c1 and was refused by the version check; user deleted it and re-tagged
