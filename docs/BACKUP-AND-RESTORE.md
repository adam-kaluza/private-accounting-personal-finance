# Backup, restore and removal

Create a backup in Files & exports. This exports a new ZIP containing approved immutable record history, the current pointer, imported originals and library index, and settings. It excludes session tokens, browser profiles, pending proposals, AI memory and previous exports. The new file is also saved in `data/exports`. Copy it to a secure backup location you control. The archive is not encrypted.

The built-in backup refuses more than 128 MiB of source data or 20,000 files. It does not discard history to meet those limits. If the limit is reached, close this edition normally and copy its entire `data` folder into a new, separate local backup folder. Keep the original unchanged and verify the copy locally before relying on it. Do not copy an actively changing workspace.

## Restore without overwriting existing records

1. Preserve your current application folder and backup unchanged.
2. Extract a fresh copy of the original application release ZIP into a **different** empty local folder. Do not launch it yet.
3. Create a folder named `data` inside that new application folder.
4. Extract your trusted backup ZIP into this new `data` folder. `records`, `documents`, and `settings.json` must be directly inside `data`, not inside another enclosing folder. Keep the backup's `BACKUP-INFO.json` there if desired.
5. Start the launcher in the new application folder. Review a few records and document previews locally. Keep the older application/backup until you are satisfied.

Do not merge backups, overwrite an active data folder, or use a backup supplied by someone you do not trust. On a second computer, move the release ZIP and your backup separately; follow these same steps. Optional AI must be set up on that computer separately.

## Update

Create a backup, close this edition through its confirmed close control, extract the newer release into a new folder, and follow the restore steps. Do not overwrite runtime files while the app is running. There is no automatic migration from any other edition.

## Uninstall

There is no system installation or service registration. First export and verify a backup. Close this edition through its close control. Keep the data folder and backup outside the program folder if you want to remove the program folder. Deleting the entire extracted folder also deletes its data and exports. No automatic uninstall script deletes records. An optional Ollama installation is managed separately using Windows Apps settings.
