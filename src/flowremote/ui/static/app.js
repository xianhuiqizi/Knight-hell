// Keep application controls in English regardless of the browser's UI language.
const fileInput = document.getElementById("task-file");
const fileName = document.getElementById("file-name");
if (fileInput && fileName) {
  const showFileName = () => {
    fileName.textContent = fileInput.files[0]?.name || "No file selected";
  };
  fileInput.addEventListener("change", showFileName);
  window.addEventListener("pageshow", showFileName);
  showFileName();
}

// Multi-source picker: show every selected file before upload and reject the
// three limits in the browser, with the server still enforcing all of them.
const multiForm = document.querySelector("[data-multi-upload]");
if (multiForm) {
  const input = multiForm.querySelector("#multi-files");
  const summary = multiForm.querySelector("#multi-file-summary");
  const list = multiForm.querySelector("#multi-file-list");
  const errorBox = multiForm.querySelector("#multi-file-error");
  const displayName = multiForm.querySelector("#multi-file-name");
  const maxFiles = Number(multiForm.dataset.maxFiles || 6);
  const maxFileBytes = Number(multiForm.dataset.maxFileBytes || 10485760);
  const maxTotalBytes = Number(multiForm.dataset.maxTotalBytes || 20971520);

  const humanSize = (bytes) => {
    if (bytes >= 1048576) return `${(bytes / 1048576).toFixed(1)} MB`;
    if (bytes >= 1024) return `${(bytes / 1024).toFixed(1)} KB`;
    return `${bytes} B`;
  };

  let touched = false;
  const validate = (files) => {
    if (files.length < 1) return "Choose between 1 and 6 source files.";
    if (files.length > maxFiles) return `Choose up to ${maxFiles} files in one run.`;
    for (const file of files) {
      if (!/\.(xlsx|csv)$/i.test(file.name)) {
        return `${file.name} is not an .xlsx or .csv file.`;
      }
      if (file.size > maxFileBytes) return `${file.name} is larger than 10 MB.`;
    }
    const total = files.reduce((sum, file) => sum + file.size, 0);
    if (total > maxTotalBytes) return "The combined upload must be 20 MB or smaller.";
    return "";
  };

  const render = (showErrors = touched) => {
    const files = Array.from(input.files || []);
    const problem = validate(files);
    list.replaceChildren();
    for (const file of files) {
      const item = document.createElement("li");
      const name = document.createElement("span");
      name.textContent = file.name;
      const size = document.createElement("span");
      size.className = "small muted";
      size.textContent = humanSize(file.size);
      item.append(name, size);
      list.append(item);
    }
    displayName.textContent = files.length
      ? `${files.length} file${files.length === 1 ? "" : "s"} selected`
      : "No files selected";
    summary.textContent = files.length
      ? `${files.length} / ${maxFiles} files · ${humanSize(
        files.reduce((sum, file) => sum + file.size, 0))} / 20 MB`
      : "";
    errorBox.hidden = !problem || !showErrors;
    errorBox.textContent = problem;
    if (problem) input.setCustomValidity(problem);
    else input.setCustomValidity("");
    return !problem;
  };

  input.addEventListener("change", () => {
    touched = true;
    render(true);
  });
  multiForm.addEventListener("submit", (event) => {
    touched = true;
    if (!render(true)) {
      event.preventDefault();
      errorBox.focus();
    }
  });
  window.addEventListener("pageshow", () => render(false));
  render(false);
}

document.getElementById("use-demo-preset")?.addEventListener("click", () => {
  const provider = document.getElementById("onboarding-provider");
  const model = document.getElementById("onboarding-model");
  if (provider) provider.value = "offline";
  if (model) model.value = "grounded-rules-v1";
  document.querySelectorAll(
    '[name="ai_enabled"], [name="rpa_enabled"], [name="connection_local_excel"], [name="connection_local_http"]'
  ).forEach((input) => {
    input.checked = true;
  });
});

// Native validation messages otherwise use the browser's language, not lang=en.
document.addEventListener("invalid", (event) => {
  const input = event.target;
  if (!(input instanceof HTMLInputElement)) return;
  input.setCustomValidity("");
  const validity = input.validity;
  if (validity.valueMissing) {
    input.setCustomValidity(input.type === "file"
      ? "Please choose an Excel workbook."
      : "Please fill out this field.");
  } else if (validity.typeMismatch) {
    input.setCustomValidity("Please enter a valid email address.");
  } else if (validity.tooShort) {
    input.setCustomValidity(`Please use at least ${input.minLength} characters.`);
  } else if (!validity.valid) {
    input.setCustomValidity("Please enter a valid value.");
  }
}, true);

for (const eventName of ["input", "change"]) {
  document.addEventListener(eventName, (event) => {
    if (event.target instanceof HTMLInputElement) {
      event.target.setCustomValidity("");
    }
  });
}

// Execution progress (Feature 2). With JavaScript on, the page advances the run
// itself and lands on the results page; with it off, the form button still works.
const progressBox = document.getElementById("execution-progress");
if (progressBox) {
  const taskId = progressBox.dataset.task;
  const resultsUrl = progressBox.dataset.results;
  const bar = document.getElementById("progress-bar");
  const label = document.getElementById("progress-label");
  const writtenCount = document.getElementById("written-count");
  const syncedCount = document.getElementById("synced-count");

  const show = (data) => {
    if (bar) bar.style.width = `${data.progress_pct}%`;
    if (label) {
      label.textContent = `${data.written} of ${data.approved} records written · ${data.progress_pct}%`;
    }
    if (writtenCount) writtenCount.textContent = data.written;
    if (syncedCount) syncedCount.textContent = data.synced;
  };

  const step = async () => {
    let response;
    try {
      response = await fetch(`/tasks/${taskId}/execution/step`, {
        method: "POST",
        headers: { Accept: "application/json" },
      });
    } catch (error) {
      return;
    }
    if (!response.ok) return;
    const data = await response.json();
    show(data);
    if (data.status === "complete") {
      window.location.assign(resultsUrl);
      return;
    }
    if (data.status === "partial") {
      window.location.reload();
      return;
    }
    window.setTimeout(step, 400);
  };

  window.setTimeout(step, 400);
}

// Multi-source normalization progress. The server owns the state; each tick is
// one deterministic step and a refresh resumes from the persisted cursor.
const normalizeBox = document.getElementById("normalize-progress");
if (normalizeBox) {
  const taskId = normalizeBox.dataset.task;
  const bar = document.getElementById("normalize-bar");
  const percent = document.getElementById("normalize-percent");
  const current = document.getElementById("normalize-current");
  const done = document.getElementById("normalize-done");
  const elapsed = document.getElementById("normalize-elapsed");
  const stageLabel = document.getElementById("normalize-stage-label");
  const errorBox = document.getElementById("normalize-error");
  let failures = 0;

  const formatDuration = (ms) => `${((ms || 0) / 1000).toFixed(1)} s`;
  const showError = (message) => {
    errorBox.textContent = message;
    errorBox.classList.add("is-error");
  };
  const update = (data) => {
    const pct = Number(data.percent || 0);
    if (bar) bar.style.width = `${pct}%`;
    if (percent) percent.textContent = `${pct}%`;
    if (current) current.textContent = data.current_file || "—";
    if (done) done.textContent = String(data.phase_done ?? 0);
    if (elapsed) elapsed.textContent = formatDuration(data.duration_ms);
    if (stageLabel) stageLabel.textContent = data.stage_label || "Normalizing";
    for (const file of data.files || []) {
      const badge = document.getElementById(`file-status-${file.id}`);
      if (!badge) continue;
      badge.textContent = file.status_label;
      badge.className = "badge";
      badge.classList.add(
        file.status === "normalized" ? "badge-accepted"
          : file.status === "attention" ? "badge-unresolved" : "badge-manual",
      );
    }
  };

  const tick = async () => {
    let response;
    try {
      response = await fetch(`/tasks/${taskId}/normalize/tick`, {
        method: "POST",
        headers: { Accept: "application/json" },
      });
    } catch (networkError) {
      failures += 1;
      if (failures < 3) {
        window.setTimeout(tick, 700);
        return;
      }
      showError("Connection lost. Refresh this page to resume from the last saved step.");
      return;
    }
    if (!response.ok) {
      let message = "The normalization step failed. Cancel and start again; uploaded files are kept.";
      try {
        const payload = await response.json();
        if (payload.error) message = payload.error;
      } catch (ignored) {
        // Keep the readable fallback.
      }
      showError(message);
      return;
    }
    failures = 0;
    const data = await response.json();
    update(data);
    if (data.status === "running") {
      window.setTimeout(tick, 360);
      return;
    }
    window.location.reload();
  };

  window.setTimeout(tick, 300);
}

// Review page: every decision reloads the page, so remember where the reviewer
// was. The server redirects with #exc-<record>, which the browser honours first;
// the saved offset is only the fallback for rows without an anchor.
const REVIEW_SCROLL_KEY = "flowremote.reviewScroll";
if (document.querySelector(".action-form")) {
  document.addEventListener("submit", (event) => {
    if (event.target instanceof HTMLFormElement && event.target.matches(".action-form")) {
      sessionStorage.setItem(REVIEW_SCROLL_KEY, String(window.scrollY));
    }
  }, true);

  if (window.location.hash.startsWith("#exc-")) {
    sessionStorage.removeItem(REVIEW_SCROLL_KEY);
  } else {
    const saved = sessionStorage.getItem(REVIEW_SCROLL_KEY);
    if (saved !== null) {
      sessionStorage.removeItem(REVIEW_SCROLL_KEY);
      const offset = Number(saved);
      if (Number.isFinite(offset) && offset > 0) {
        requestAnimationFrame(() => window.scrollTo(0, offset));
      }
    }
  }
}

// AI connection window (Feature 3). The header link still works as a normal
// settings page when JavaScript is unavailable.
const aiDialog = document.getElementById("ai-settings-dialog");
if (aiDialog) {
  const opener = document.querySelector("[data-ai-settings-open]");
  const closeButton = aiDialog.querySelector("[data-ai-settings-close]");
  const form = document.getElementById("ai-settings-form-modal");
  const provider = document.getElementById("ai-provider");
  const model = document.getElementById("ai-model");
  const baseUrl = document.getElementById("ai-base-url");
  const apiKey = document.getElementById("ai-api-key");
  const keyStatus = document.getElementById("ai-key-status");
  const status = document.getElementById("ai-settings-status");

  const setStatus = (message, isError = false) => {
    status.textContent = message;
    status.classList.toggle("is-error", isError);
  };

  const fill = (settings) => {
    provider.value = settings.provider;
    model.value = settings.model || "";
    baseUrl.value = settings.base_url || "";
    apiKey.value = "";
    keyStatus.textContent = settings.key_configured
      ? `Saved key: ${settings.key_hint} (${settings.key_source})`
      : "No saved API key. A server environment key may still be used.";
  };

  const load = async () => {
    setStatus("");
    try {
      const response = await fetch("/settings/ai", {
        headers: { Accept: "application/json" },
      });
      if (!response.ok) throw new Error("Could not load AI settings.");
      fill(await response.json());
    } catch (error) {
      setStatus(error.message || "Could not load AI settings.", true);
    }
  };

  opener?.addEventListener("click", (event) => {
    if (typeof aiDialog.showModal !== "function") return;
    event.preventDefault();
    fill({ provider: "offline", model: "gpt-6-astra", base_url: "", key_configured: false });
    aiDialog.showModal();
    load();
  });
  closeButton?.addEventListener("click", () => aiDialog.close());
  aiDialog.addEventListener("click", (event) => {
    if (event.target === aiDialog) aiDialog.close();
  });
  form?.addEventListener("submit", async (event) => {
    event.preventDefault();
    setStatus("Saving…");
    try {
      const response = await fetch(form.action, {
        method: "POST",
        headers: {
          Accept: "application/json",
          "Content-Type": "application/x-www-form-urlencoded",
        },
        body: new URLSearchParams(new FormData(form)),
      });
      const data = await response.json();
      if (!response.ok || !data.ok) throw new Error(data.error || "Could not save settings.");
      fill(data.settings);
      form.querySelector('[name="clear_key"]').checked = false;
      setStatus("Connection settings saved. No test request was sent.");
    } catch (error) {
      setStatus(error.message || "Could not save settings.", true);
    }
  });
}
