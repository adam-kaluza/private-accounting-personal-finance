# Troubleshooting

**Nothing opens:** Extract the entire ZIP to a writable local folder first. Keep `runtime`, `app` and the launcher together. Run `Run fictional self-tests.cmd` to check the package without touching your records. A SmartScreen/antivirus warning should be investigated; compare the published checksum and source, and do not broadly disable protection.

**Path too long:** Choose a shorter extraction path, such as a local folder directly under your user directory. Windows installations can limit file paths to 260 characters. This release refuses a data-folder path longer than 155 characters before opening records so there is room for versioned filenames. Keep the entire application folder together when moving it.

**App window closed:** Reopen the same launcher. If its own service is still running, the launcher checks its control endpoint and opens that session. Drafts may live only in the original browser tab; do not assume a new tab restores them. Nothing is resent automatically.

**Data folder in use:** Another instance holds it. Close that instance normally, after saving approved work, then retry. Do not delete lock files or kill unrelated applications. Separate extracted copies have separate storage.

**Local model cannot start:** Confirm the model has been downloaded and the official Ollama executable path is correct. A cloud-only tag cannot be used. The app does not start an install or download. Existing model sessions are preserved. Manual features remain available.

**Local model takes too long:** Wait for the one request to finish or time out. Avoid repeated submissions. Use fewer documents, shorter notes and a model that fits your hardware. No automatic retry occurs and no response is saved automatically.

**Proposal cannot be approved:** Read its missing-information questions and validation warnings. Fix the draft and create a fresh proposal. Plain decimal amounts and exact dates are required. Duplicates need explicit acknowledgement. Another approved change can make the proposal stale; rebuild it against the current revision.

**PDF has no text:** It may be a scan or encrypted. Use trusted local OCR outside the app or enter notes manually. Do not assume an empty preview means an empty statement.

**CSV has no rows:** Use the canonical headers in the example CSV. UTF-8 encoding and ISO dates are required; no ambiguous dates or bank-specific mappings are guessed. XLSX formula amounts require separately confirmed numeric values.

**Export is missing:** Exports are saved in this edition's `data/exports`, as well as offered for download. Browser downloads may use a different folder. Re-exporting makes a new name; it does not overwrite the earlier file.

**Saved records are unreadable:** Preserve the whole folder and restore a known good backup into a new extraction. Do not edit or delete historical JSON files. Support requests should use fictional reproduction files, version and fixed error text—not financial records, private logs or screenshots containing personal information.
