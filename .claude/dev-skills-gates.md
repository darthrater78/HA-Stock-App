# Dev Skills gate state
Track: work commit
Mode: semi-autonomous (approved 2026-09-24) — commits and the tag still require the user's approval
Origin: darthrater78/HA-Stock-App (not a fork)
Standards: n/a — HA integration, no auth/Docker; at-rest: HA config entry storage (HA-managed)
Version: 2.7.14
Updated: 2026-09-24

🔢 VERSION    ⬜
🔨 BUILD      ⬜
🔒 SECURITY   ✅ 0 Critical, 0 High open — 2 Low open (not blocking a work commit)
    Fixed: gate timeout (High); Python pin, actionlint workflow, release set -e,
      manifest dependency audit (Medium); job-level write perm, CI-run race, fetch-depth (Low)
    Open Low: no environment: approval on release; paths-ignore vs required checks
    Unverified: Dependabot alerts repo setting (user to confirm)
    Evidence: actionlint 1.7.12 clean; pip-audit 2.10.1 clean; 29 tests pass
📄 DOCS       ⬜
📦 RELEASE    ⬜
🚀 SHIP       ⬜
