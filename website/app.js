"use strict";
(() => {
  const status = document.getElementById("release-status");
  const command = document.getElementById("install-command");
  const copy = document.getElementById("copy-command");
  const copyStatus = document.getElementById("copy-status");
  const fields = ["repository_url", "release_url", "zip_url", "checksum_url", "installer_url", "verification_url", "guide_url", "issues_url"];
  function approvedURL(value) {
    if (typeof value !== "string" || value.length > 2000) return null;
    try {
      const parsed = new URL(value);
      if (parsed.protocol !== "https:" || parsed.hostname !== "github.com" || parsed.username || parsed.password || parsed.port || parsed.hash) return null;
      return parsed.href;
    } catch (_) { return null; }
  }
  function installConfig(config) {
    if (!config || typeof config !== "object" || Array.isArray(config)) throw Error("Invalid release configuration.");
    if (typeof config.version !== "string" || !/^\d+\.\d+\.\d+(?:-[a-z0-9.-]+)?$/i.test(config.version)) throw Error("Invalid release version.");
    if (config.status !== "pre-release") throw Error("Release status requires review.");
    document.querySelectorAll("[data-version]").forEach(node => { node.textContent = config.version; });
    document.querySelectorAll("[data-status]").forEach(node => { node.textContent = config.status; });
    const repository = approvedURL(config.repository_url);
    if (repository && !/^https:\/\/github\.com\/[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/.test(repository)) throw Error("Invalid repository URL.");
    if (config.tag !== "v" + config.version) throw Error("Release tag does not match version.");
    let complete = Boolean(repository && /^[a-f0-9]{64}$/i.test(config.zip_sha256 || "") && /^[a-f0-9]{64}$/i.test(config.installer_sha256 || ""));
    const urls = {};
    for (const field of fields) {
      const url = approvedURL(config[field]);
      urls[field] = url && repository && (url === repository || url.startsWith(repository + "/")) ? url : null;
      if (!urls[field]) complete = false;
    }
    if (urls.release_url !== repository + "/releases/tag/" + config.tag) complete = false;
    if (!urls.zip_url || !urls.zip_url.startsWith(repository + "/releases/download/" + config.tag + "/")) complete = false;
    if (!urls.installer_url || !urls.installer_url.startsWith(repository + "/releases/download/" + config.tag + "/")) complete = false;
    for (const field of fields) {
      const url = urls[field];
      document.querySelectorAll(`[data-link="${field}"]`).forEach(node => {
        if (!url || (!complete && ["zip_url", "installer_url", "checksum_url"].includes(field))) { node.removeAttribute("href"); node.setAttribute("aria-disabled", "true"); return; }
        node.href = url; node.removeAttribute("aria-disabled"); node.rel = "noopener noreferrer";
      });
    }
    const installCommand = typeof config.install_command === "string" && config.install_command.length <= 16000 ? config.install_command.trim() : "";
    if (complete && installCommand) {
      command.value = installCommand;
      copy.disabled = false;
      status.textContent = "";
    } else {
      command.value = ""; copy.disabled = true;
      status.textContent = "Release links are being prepared. Please check back shortly.";
      copyStatus.textContent = "The tested command will be available with the release.";
    }
  }
  copy.addEventListener("click", async () => {
    if (copy.disabled || !command.value) return;
    copy.disabled = true;
    try {
      if (!navigator.clipboard || !navigator.clipboard.writeText) throw Error("Clipboard unavailable.");
      await navigator.clipboard.writeText(command.value);
      copyStatus.textContent = "Copied. Review the command, then paste it into Windows PowerShell.";
      copy.textContent = "Copied";
    } catch (_) {
      command.focus(); command.select();
      copyStatus.textContent = "Automatic copy is unavailable. The command is selected; press Ctrl+C to copy it.";
      copy.textContent = "Copy command";
    } finally { copy.disabled = false; }
  });
  fetch("./release.json", {cache:"no-store", credentials:"omit", redirect:"error"})
    .then(response => { if (!response.ok) throw Error("Release links are unavailable."); return response.json(); })
    .then(installConfig)
    .catch(() => { status.textContent = "Release links are temporarily unavailable. Please reload this page later."; copy.disabled = true; });
})();
