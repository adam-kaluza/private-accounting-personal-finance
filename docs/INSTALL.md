# Windows installation

The portable ZIP and the optional per-user installer both run the personal-finance edition locally. Internet is needed to download release files. Normal manual recordkeeping does not require internet or a model. The installer does not install Ollama, download models, enable Windows features, change execution policies, or restart another application.

## Portable ZIP

Download the Windows x64 application ZIP from this project's GitHub release, compare its SHA-256 with the published checksum, extract the whole ZIP into a new short local folder, and open `Start Private Accounting.cmd`. Data for a portable copy lives in that copy's `data` folder. Preserve the complete folder when moving it.

## Optional installer

Use the version-pinned command on the project's GitHub Pages download page. It downloads the installer, checks its published SHA-256, and invokes the verified script text in the current PowerShell session. The installer separately verifies the application ZIP before extracting any member. Read the command and script before running them. GitHub downloads and the public website use internet access; they do not receive local financial records.

The command does not alter execution policy. It refuses explicit Restricted or AllSigned policies and restricted language modes; an organization can apply additional controls. If Windows or your organization refuses this installer, use the portable ZIP. Do not disable your security controls or change execution policy to run this tool. This release is unsigned and has no independent security certification.

The default managed installation is:

```text
%LOCALAPPDATA%\PrivateAccountingPersonalFinance\
    versions\<version>\        Application files for that release
    data\                      Persistent records for this managed edition
    Start Personal Finance <version>.cmd
```

Open the version-specific launcher at the installation root, or the optional shortcut. It supplies the persistent data path explicitly. The original launcher inside a version's application directory is still the portable launcher; opening it directly uses that directory's separate portable `data` folder.

The installer refuses a nonempty destination unless it already has this installer's ownership record. It preserves existing files, records, and release versions. Reinstalling an unchanged version verifies its files and returns `already-installed`; modified application files are not overwritten. Future versions receive separate program folders and launchers. Back up records and close this managed edition normally before intentionally switching versions; the installer itself does not restart anything.

## Installer options

Where your existing execution policy permits unsigned local script files, you can also independently verify the downloaded installer and invoke it with PowerShell, for example:

```powershell
& .\install.ps1 -DesktopShortcut
```

- `-DesktopShortcut` creates a shortcut named `Private Accounting Personal Finance <version>`. An existing shortcut with that name is preserved and reported. The original Private Accounting shortcut is not changed.
- `-Launch` explicitly opens the newly installed edition. Without this flag the installer only prepares files and prints the launcher location.
- `-InstallRoot 'C:\A-Short-Local-Folder'` selects a different empty or installer-owned destination. The persistent `data` path must be at most 155 characters. Linked/redirected destinations and network shares are refused.
- `-ArchivePath 'C:\Downloads\The-Release.zip'` installs an already downloaded matching release without a network request. The same pinned archive checksum is required.
- `-ShortcutDirectory 'C:\An-Existing-Local-Folder'` chooses where to place the requested shortcut; it requires `-DesktopShortcut`.

## Removal and recovery

Export and verify a backup first. Close this edition through **Settings & help → Shut down workspace**. To remove program files, remove only the version folder and its version-specific launcher/shortcut that you no longer want. Preserve the `data` folder, installation ownership record, and backups if you may return later. There is no automatic uninstall that deletes records.

If installation fails, the installer cleans only its own newly created temporary staging directory. Existing versions and records are left in place. An interruption can leave installer-owned temporary files; never delete a whole data folder to fix an installation problem. Use a new separate installation folder or consult the error before retrying. Checksums verify consistency with the published files; they are not a defense against a compromised publisher account or a malicious local program.
