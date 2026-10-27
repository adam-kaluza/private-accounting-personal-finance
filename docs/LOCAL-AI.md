# Optional local AI setup

All manual entry, plans, review, document preview and exports work without AI. No model is included because weights are large, hardware needs vary, and each model has its own license.

1. While you have internet access, install Ollama from [its official Windows download](https://ollama.com/download/windows). Review its terms and the selected model's license. The app does not download or install it for you.
2. Download a local model using Ollama's own controls/CLI before disconnecting. For a small fictional smoke test, one possible command is `ollama pull qwen2.5:0.5b`. Small models can make poor extraction decisions; this is an example, not a quality endorsement. Choose a model your RAM and storage support. Do not choose a cloud model.
3. Close the new public app if needed only after saving approved work. Ensure Ollama is available on PATH, or provide its official executable's full local path in Settings. No system-wide setting change is required by this app.
4. In Settings & help, enter the exact downloaded model name and select **Start local AI**. This starts a separate hidden `ollama serve` child with cloud features disabled; it does not restart an already running session or send a test prompt.
5. In Add information, paste a fictional note first. Select only the documents you intend to include. Click Analyze once, wait for the status to finish, then review any proposal and questions.

During use, the app communicates only with its own loopback Ollama process. It never signs in, pulls a model, calls a remote server, or falls back to a cloud model. Failed/slow requests do not retry automatically. If a request reaches the 120-second response timeout, results are discarded; the model may finish its internal work afterward. Do not immediately submit repeated copies. Use smaller batches; no financial entries are saved until approval.

No bundled model means the release's mocked protocol tests verify the integration contract, not every model's accuracy or your GPU compatibility. Consult TEST-REPORT.md for the actual release's additional model test evidence.

Publisher references: [Ollama local-only configuration](https://docs.ollama.com/faq#how-do-i-disable-ollamas-cloud-features), [Ollama MIT source license](https://github.com/ollama/ollama/blob/main/LICENSE). Model licenses are separate and are not granted by this app's MIT license.
