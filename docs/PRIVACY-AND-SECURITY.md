# Privacy boundaries

The application listens only on `127.0.0.1` at a random local port. Each launch uses a random bearer token. API requests require that token and the exact local Host/Origin; cross-origin requests are refused. There are no analytics, cloud APIs, remote fonts/CDNs, ads, remote error reports or app update calls. The Python process additionally rejects non-loopback socket connections and external DNS resolution. Imported document text is data, not an instruction source.

The app uses an isolated Edge profile with extensions and synchronization disabled when Edge is available. Browser/OS telemetry and other installed programs are outside this application's control. Local-only processing is not disk encryption, protection from other programs running as you, or proof that the whole PC has no network traffic. Use a local nonsynchronized folder, suitable device access controls and disk encryption. Do not open the data folder with a cloud-backed assistant.

Optional Ollama starts only after your explicit action. It uses its own hidden process and loopback port, `OLLAMA_NO_CLOUD=1`, no proxy environment, and requires local model parameter metadata. Cloud model names/remote-model responses are refused. Only `/api/version`, `/api/show` and `/api/chat` are called; there are no model pull, web-search, tool-execution or cloud fallback paths. You still need to trust your installed Ollama executable and downloaded model. This is not a defense against a compromised executable or operating system.

The service keeps no request-body, model-response or access logs. Approved finance entries and imported originals are intentionally stored on disk. Exports and backups contain your information in plaintext. Pending proposals/notes are memory-only; do not assume they survive shutdown. The local browser session token is stored in sessionStorage and a local process-control file and removed from the address bar by the frontend. Never share a live local URL/token or a used data directory.

## Stronger isolation with Windows Sandbox

For a separately isolated session, use a supported Windows edition with Windows Sandbox already installed. Run `Create offline Sandbox configuration.cmd` to create an edition-specific `.wsb` file. Read the generated configuration, then open it yourself when no other Sandbox is running. The generator does not stop, replace or restart any existing Sandbox.

The generated configuration disables networking, clipboard, printer, audio and video redirection. It maps the extracted application read-only and this edition's `data` folder read-write so approved files persist. It does not discover other workspaces. Windows Sandbox itself and its existing feature installation are not bundled.

The basic app works in that environment; optional AI is not automatically provisioned there. An offline Sandbox needs a separately staged Ollama runtime and model files. This release does not automate that provisioning or claim its optional Sandbox configuration was exercised in the user's existing private session.

## Release hygiene

The build script accepts only enumerated source/docs/examples/tests plus the checksum-pinned official runtime and pypdf wheel. It never searches the old application or any data folder. Application data, sessions, test temporary folders, output files and browser profiles are excluded. A staged-content scan and per-file SHA-256 manifest accompany the release. These checks are evidence about this package, not a general security certification.
