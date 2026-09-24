## Handoff: CI workflow audit + v2.7.15 market-open fix
**Goal:** Harden CI workflows (audit findings) and fix stale prices after the opening bell.
**Current state:** Done and shipped. PR #55 (CI hardening) and PR #56 (v2.7.15) merged;
v2.7.15 tagged at 9c18db2 and published by release.yml (gate, version check, `release` env all ran).
**Gate status:** 🔢✅ 🔨✅ 🔒✅ 📄✅ 📦✅ 🚀✅ — v2.7.15 complete (see dev-skills-gates.md)
**Mode:** this session ran semi-autonomous; the next session asks again.
**Key files:**
- custom_components/ha_stock_app/__init__.py — `_market_open` (9:30 forced fetch, then optional
  event) and shared `_refresh_prices_now` used by `_eod1_summary`
- .github/workflows/release.yml — gate job (timeout 35, 90s empty-run retry), `release` environment
- .github/workflows/ci.yml — Python 3.11/3.14 matrix; paths-ignore warning re required checks
- .github/workflows/lint-workflows.yml, dependency-audit.yml — actionlint 1.7.12 (sha256 pinned),
  weekly pip-audit of manifest.json requirements (Dependabot can't read manifest.json)
**Decisions made:**
- 9:30 fetch always runs, independent of the market-open notification toggle
- PR paths-ignore kept; must be removed before any CI job becomes a required check
- README top links repo + current release notes; bump that link every release (Gate 1)
- Tag only after the release PR merges — v2.7.15 was first tagged on 2c822c1 and refused
**Open items:**
- Verify on live HA next trading day: stock sensors / Last Stock Poll update at 9:30
- Known limit: a 9:30:00 quote can still be the prior close; next poll corrects it
- Early-close days: EOD summary still fires at 16:05 (fixed time, noted in v2.7.13)
- Settings: confirm Dependabot alerts on; optionally add a required reviewer to `release` env
**Shell environment:** remote container bash
**Next step:** confirm the 9:30 update on HA; then pick up the next feature or fix.
