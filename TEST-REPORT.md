# Release validation — 1.1.0

Windows x64, unsigned pre-release. All finance records, notes, documents, and installer fixtures used for testing were fictional. Existing installations, client documents, private chats, and private workspaces were not inspected or changed. The application retains the 1.0.1 finance behavior and hardening fixes; 1.1.0 adds public distribution tooling.

## Application and source tests

The complete source suite ran 183 tests: 181 passed and 2 skipped because this Windows account lacks symbolic-link creation privilege. Separate actual Windows junction and hardlink refusal tests passed. The source suite includes 25 installer tests, 15 publication-audit tests, and 4 dependency-bootstrap tests.

The portable application ZIP excludes the separately pinned installer and its 25 tests to avoid a circular archive hash. It contains 158 application, parser, server, packaging, bootstrap and audit tests. The final extracted-ZIP result is recorded in the release's separate Verification-1.1.0.json asset.

Coverage includes exact cents and large totals; incomplete values and classification; duplicate acknowledgement; stale/double approvals; immutable history and interrupted commits; saved-entry editing/deletion; dated budgets, refunds and unknown debts; source references; CSV/XLSX/PDF/ZIP parsing and bounds; inert exports; loopback Host/Origin/token checks; rejected non-loopback Python destinations; request/backup limits; atomic annotation; startup failure cleanup; shutdown draining; file-import recovery; backup restore; and actual isolated launcher shutdown/reopen.

A 1,001-row fictional ledger was independently totaled, saved/reopened, and exported for all dates and a 501-row reporting period. Independent openpyxl readback confirmed literal text, ordinary numeric amounts, exact oversized totals as text, and no generated formulas. These checks do not certify financial judgment or arbitrary document extraction accuracy.

## Browser checks

Headless Edge with fresh fictional contexts: 13 application acceptance groups, 16 adversarial UI groups, and 11 landing-page groups passed. There were no screenshots, JavaScript page errors, or unpermitted external page requests. The landing-page suite uses mocked release metadata and downloads; actual published asset checks belong in the separate verification receipt.

Checks include setup and explicit approval, draft retention, pending-action locks, invalid/unknown inputs, correction and deletion, interrupted approvals, duplicate overrides, five exports, saved-data reopen, exact large currency display, narrow widths, keyboard navigation, project-subpath hosting, command copying/fallback, link configuration, and failure on malformed release metadata.

## Windows installer and bootstrap

Installer tests cover fresh/repeated/versioned installs, preservation of fictional records, refusal to overwrite changed files or unowned directories, wrong hashes, partial download cleanup, traversal and Windows path collisions, directory-as-file tricks, archive size/expansion limits, mapped/network and linked paths, path-length limits, explicit shortcut behavior, and a temporary Windows rename lock. The installer never starts an existing app or changes Windows execution policy.

The public command first checks for restrictive explicit policies, downloads a pinned installer, verifies SHA-256, then invokes the verified text. Separate fictional command tests check successful execution, changed-content rejection, and refusal under explicit Restricted/AllSigned policies. These are execution tests in addition to the audit's limited structural checks; a static pattern check alone is not proof of PowerShell semantics.

A fresh temporary bootstrap downloaded the official pinned Python 3.14.10 and pypdf 6.21.2 archives, verified their hashes, and prepared the runtime without touching another app. Source-clone downloads require explicit --download; the release ZIP includes the pinned archives for offline rebuilding. GitHub's Windows workflow reruns this clean-clone path; its live result is available in Actions.

## Package and publication boundaries

The builder reads an explicit source allowlist and pinned public dependencies. The publication audit reuses the existing privacy patterns, rejects linked paths and unexpected staged files, verifies ZIP manifest bytes, and checks version/tag/download/hash consistency. Neither tool traverses a private workspace. Only enumerated public source is uploaded; generated runtime data, browser profiles, logs, model caches and populated test folders are excluded.

Final exact-ZIP installation, reproducibility, public download readback, and Pages checks are recorded in Verification-1.1.0.json beside the release assets. The website distributes software and does not accept financial-data uploads. GitHub may log website visits; browser/OS/Ollama behavior remains outside the app's own loopback controls.

## Limits

No test suite guarantees a bug-free release. The package is unsigned and has no independent security audit. Windows 10/ARM64, every model/hardware combination, hostile same-user processes, whole-PC network isolation, and an end-user GUI session on a newly installed OS have not been validated. Optional local AI is not bundled and never saves suggestions automatically. See docs/PRIVACY-AND-SECURITY.md and docs/LIMITATIONS.md.
