# Private Accounting · Personal finance

A portable Windows application for reviewing income and spending, keeping budgets and debt notes, organizing local documents, and exporting your records. Optional AI runs through a separate local Ollama session. Manual features need no AI, account, subscription, Python installation, Excel, or internet connection.

**Version 1.1.0 · Windows x64 · MIT application license**

[Download and installation](https://adam-kaluza.github.io/private-accounting-personal-finance/) · [Releases](https://github.com/adam-kaluza/private-accounting-personal-finance/releases) · [Report an issue](https://github.com/adam-kaluza/private-accounting-personal-finance/issues)

This is an unsigned pre-release. Use fictional data first. The published website distributes the software; it does not receive financial records. Read the [installation guide](docs/INSTALL.md) for the optional per-user Windows installer and its checksum verification.

## Start in three steps

1. Right-click the downloaded ZIP → **Extract All**. Choose a short, writable local folder outside OneDrive, Dropbox, or other synchronized folders. Open the resulting **PrivateAccounting** folder. Do not run from inside the ZIP. The launcher checks for overly long Windows paths before creating records.
2. Open the extracted folder and double-click **Start Private Accounting.cmd**. Keep the whole folder together. The app opens in its own Edge window where available, otherwise your default browser.
3. Read the first-run information. Set your goals and reporting dates, review the proposal, then approve it. Try **Prepare sample data** in Settings & help before entering real information; the demo also requires approval.

The app has one interface: **Dashboard**, **Transactions**, **Plans & debts**, **Add information**, **Review**, **Files & exports**, and **Settings & help**. The dashboard summarizes approved records only. Internal modules are included so users do not have to run them individually.

## Typical workflow

- Enter a transaction, or select a file in **Add information**. File selection sends its bytes only to this app's loopback service on your computer.
- Preview the content. Importing a document preserves a separate original copy; it does not approve financial entries.
- For canonical CSV/XLSX rows, create a proposal. For prose/PDF text, optionally use local AI after configuring it in Settings, or enter the records yourself.
- In **Review**, correct missing or unclear facts. Confirm duplicates deliberately. Approve only values you have checked.
- Export XLSX, CSV, JSON, a printable HTML report, or a complete records/documents backup from **Files & exports**. Open the printable report and choose Print → Save as PDF for a PDF copy.

Dates use `YYYY-MM-DD`. Amounts use exact USD decimals without currency symbols or commas. Income is positive; spending is negative. Transfers, loans and refunds are kept separate from ordinary income and expenses. Plans are not transactions, and cash movement is not an account balance.

## What's included

- The app and readable source, a bundled Python 3.14.10 runtime, and pypdf 6.21.2 for local PDF text previews.
- Fictional CSV/notes examples, automated tests, build tools, dependency checksums, component inventory and licenses.
- No personal records, preconfigured users, model weights, cloud integrations, or tax-preparation features.

Ollama and an appropriate downloaded model are **optional and not bundled**. Read [local AI setup](docs/LOCAL-AI.md). The app never pulls a model or installs a dependency silently. Initial downloads can be done before disconnecting; normal finance work is offline.

## Requirements

Windows 10/11 x64 with a current Edge or compatible browser; x64 is the only packaged architecture. Windows 11 is the validation host; Windows 10 has not been separately tested. Allow approximately 150 MB for the program and tests, plus your documents, immutable record history, browser profile and backups. Typical small ledgers need no dedicated GPU. A local AI model has separate RAM/storage requirements; start with small fictional batches and follow its publisher's hardware guidance. ARM64/macOS/Linux are not supported by this ZIP.

Windows Sandbox is optional, not required for normal launch. An optional configuration generator is included for supported Windows editions with Sandbox already enabled; see [offline setup](docs/PRIVACY-AND-SECURITY.md). It does not enable Windows features or restart your computer.

## Storage, closing, updates

For a portable ZIP extraction, data lives in the **data** folder beside the launcher. The optional installer uses its own persistent data folder under `%LOCALAPPDATA%\PrivateAccountingPersonalFinance\data`, separate from versioned program files. The exact active location appears in Settings. Approved revisions and imported originals persist after the app closes. Unsaved form drafts and notes live in the browser tab's memory and can be lost on browser reload/closure; pending proposals are lost when the local service shuts down. Closing only the browser window leaves the local service available; use the app's confirmed **Shut down workspace** control to stop this edition and its own optional AI child. Existing Ollama sessions are not stopped.

Before updating or uninstalling, create and verify a backup. See [backup and restore](docs/BACKUP-AND-RESTORE.md). Never replace or delete a data folder to resolve an error.

## Read more

- [User guide](docs/USER-GUIDE.md)
- [Privacy and security boundaries](docs/PRIVACY-AND-SECURITY.md)
- [Supported formats and limitations](docs/LIMITATIONS.md)
- [Troubleshooting](docs/TROUBLESHOOTING.md)
- [Build and test instructions](docs/BUILD.md)
- [Release notes](CHANGELOG.md)
- [Application license](LICENSE) and [third-party notices](THIRD-PARTY-NOTICES.md)

This edition is a recordkeeping tool. It does not connect to banks, move money, perform verified investment/tax calculations, or file returns. AI suggestions are fallible and always need review.
