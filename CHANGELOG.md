# 1.1.0

Public distribution update. Adds a GitHub Pages download site, a separately distributed checksum-pinned per-user Windows installer, clean-clone dependency bootstrap, and fictional Windows CI. Installer versions and persistent data have separate locations; no previous Private Accounting installation is migrated or modified. Optional AI remains opt-in and unbundled. Finance behavior retains the 1.0.1 hardening fixes.

# 1.0.1

Hardening release validated with fictional records and files. Keeps existing releases and other editions separate.

- Preserve setup and input drafts during navigation; disable navigation and edits while a request is pending. Require explicit transaction and debt dates, retain unknown classifications, and reconcile interrupted approvals before offering another action.
- Attach required review questions before a proposal can be approved. Reject ambiguous HTTP framing, malformed authorization, and incomplete request bodies; bound request workers, idle connections, backup size, and download handles. Drain in-flight requests before releasing the workspace lock.
- Reject linked storage paths and hardlinked files, including session/configuration paths. Release startup locks and clean temporary files when startup or atomic writes fail.
- Validate actual local-model output shape and size, reject incomplete or oversized responses, and require local model metadata. No response is automatically saved.
- Tighten spreadsheet coordinate and XML resource checks, provide accurate multiline CSV source locations, and preserve large export totals as exact text when spreadsheet numeric precision would be insufficient. Show the selected reporting period correctly.
- Add security, parser, packaging, realistic-size ledger, and adversarial browser regressions. Preserve existing release privacy checks and pinned dependency verification.

# 1.0.0 — 2026-10-26

First standalone public personal-finance edition. One launcher and interface, portable Windows runtime, exact-decimal ledger, explicit approval, duplicate and stale-edit checks, immutable record history, dated budgets/debts, local document preview/library, optional local AI, and separate reports/backups.

New independent data format. No automatic import from other editions. No tax-preparation interface, shared private workspace, existing sessions, model weights or private content. See docs/LIMITATIONS.md and TEST-REPORT.md before distribution.
