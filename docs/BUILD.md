# Build and validate

The ZIP includes application source, fictional tests and checksum-pinned dependency archives. No repository clone, package manager or internet connection is needed to rebuild it.

The Git repository contains source and dependency pins; generated runtime/dependency folders and archives are excluded. On Windows, a fresh clone needs an existing Python installation for the one-time explicit bootstrap:

```powershell
python tools/bootstrap_runtime.py --download
.\runtime\python.exe tools/run_tests.py
.\runtime\python.exe tools/build_release.py
```

The bootstrap downloads only the pinned official Python and pypdf archives, verifies their SHA-256 values before extraction, and refuses differing existing dependency files. Subsequent builds can run offline. It never downloads AI models. The GitHub Windows test workflow exercises this clean-clone route. Its commit-pinned Actions receive read-only repository access; the separately triggered Pages workflow receives deployment permission only for its deploy job.

From the extracted application folder, run:

```bat
runtime\python.exe tools\run_tests.py
runtime\python.exe tools\build_release.py
```

The build writes `dist/Private-Accounting-Personal-Finance-1.1.0-Windows-x64.zip`, a `.sha256` file and `RELEASE-MANIFEST.json`. It reads only the explicit source list inside `tools/build_release.py` and the two dependency archives. It does not walk a data folder. ZIP entry order/timestamps are fixed; building unchanged files with the included runtime should yield the same bytes. Editing source or TEST-REPORT.md intentionally changes the output digest.

For a new dependency version, verify its upstream publisher, release and license, obtain the official archive and SHA-256, update the pinned constants, update notices/manifest, and rerun the complete acceptance suite. Do not copy packages out of a user's installed environment into a public release.

## Tests

`Run fictional self-tests.cmd` runs the Python unit and loopback HTTP tests against temporary fictional stores under tests/. It never opens the program's data folder. The test process uses a loopback socket; security software must permit that local communication. A loopback permission error is an environment failure, not proof the UI is healthy.

Browser acceptance uses `tests/browser_smoke.cjs` and `tests/browser_adversarial.cjs` with Node and Playwright installed separately on the developer's machine; these development tools are not necessary for normal use and are not bundled. Run each with a fresh extracted application path and a local Playwright module path as documented in its header. Each creates a new fictional data directory, blocks every non-loopback browser request, uses a fresh browser context, records no screenshots, checks user workflows, and closes only its own process.

The shipped manifest lists every packaged file except the manifest itself. Verify a download with Windows PowerShell:

```powershell
Get-FileHash -LiteralPath '.\Private-Accounting-Personal-Finance-1.1.0-Windows-x64.zip' -Algorithm SHA256
```

Compare with the checksum delivered alongside the ZIP through a trusted channel. The package is not code-signed. Tests, checksums and source availability are useful review evidence, not a guarantee that all environments or untrusted inputs are safe.
