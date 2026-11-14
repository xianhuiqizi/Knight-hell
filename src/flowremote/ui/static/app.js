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

// Human review cards: AI advice, confirm and skip. All AI output is advisory:
// the presenter must confirm it, and every decision is validated server-side.
const issueCards = document.querySelectorAll("[data-issue-card]");
if (issueCards.length) {
  const taskId = document.body.dataset.taskId;
  const showIssueError = (card, message) => {
    const box = card.querySelector("[data-issue-error]");
    if (!box) return;
    box.hidden = false;
    box.textContent = message;
  };
  const clearIssueError = (card) => {
    const box = card.querySelector("[data-issue-error]");
    if (box) {
      box.hidden = true;
      box.textContent = "";
    }
  };
  const setBusy = (card, busy) => {
    card.querySelectorAll("button").forEach((button) => {
      button.disabled = busy;
    });
  };

  issueCards.forEach((card) => {
    const form = card.querySelector("[data-issue-form]");
    if (!form) return;
    const aiButton = card.querySelector("[data-ai-suggest]");
    const skipToggle = card.querySelector("[data-skip-toggle]");
    const skipBox = card.querySelector("[data-skip-box]");
    const skipButton = card.querySelector("[data-skip]");
    const skipDirect = card.querySelector("[data-skip-direct]");
    const aiBox = card.querySelector("[data-ai-result]");

    aiButton?.addEventListener("click", async () => {
      clearIssueError(card);
      setBusy(card, true);
      if (aiBox) {
        aiBox.hidden = false;
        aiBox.className = "ai-suggestion-box";
        aiBox.textContent = "Asking AI for a suggestion…";
      }
      try {
        const response = await fetch(
          `/tasks/${taskId}/normalize/issues/${card.dataset.issueId}/ai-suggest`,
          { method: "POST", headers: { Accept: "application/json" } },
        );
        let data;
        try {
          data = await response.json();
        } catch (parseError) {
          throw new Error("The AI suggestion returned an unreadable response.");
        }
        if (!response.ok) {
          throw new Error(data.error || "The AI suggestion failed.");
        }
        for (const [field, value] of Object.entries(data.fields || {})) {
          const input = form.querySelector(`[name="${field}"]`);
          if (input) input.value = value;
        }
        if (aiBox) {
          aiBox.hidden = false;
          aiBox.className = "ai-suggestion-box";
          aiBox.textContent = "";
          const title = document.createElement("strong");
          title.textContent = `${data.source_label || "AI suggestion"} · ${Math.round(
            Number(data.confidence || 0) * 100,
          )}%`;
          const reason = document.createElement("p");
          reason.dataset.i18nSkip = "true";
          reason.textContent = data.reason || "";
          aiBox.append(title, reason);
          if (data.evidence && data.evidence.length) {
            const evidence = document.createElement("ul");
            evidence.dataset.i18nSkip = "true";
            for (const item of data.evidence) {
              const li = document.createElement("li");
              li.textContent = item;
              evidence.append(li);
            }
            aiBox.append(evidence);
          }
          if (data.warning) {
            const warning = document.createElement("p");
            warning.className = "ai-fallback-inline";
            warning.textContent = data.warning;
            aiBox.append(warning);
          }
        }
      } catch (error) {
        showIssueError(card, error.message || "The AI suggestion failed.");
        if (aiBox) aiBox.hidden = true;
      } finally {
        setBusy(card, false);
      }
    });

    form.addEventListener("submit", async (event) => {
      event.preventDefault();
      clearIssueError(card);
      setBusy(card, true);
      const changes = {};
      form.querySelectorAll("input[name], select[name]").forEach((input) => {
        if (input.name !== "decision_id") changes[input.name] = input.value;
      });
      const decisionId = form.querySelector('[name="decision_id"]')?.value || "";
      try {
        const response = await fetch(
          `/tasks/${taskId}/normalize/issues/${card.dataset.issueId}/confirm`,
          {
            method: "POST",
            headers: {
              Accept: "application/json",
              "Content-Type": "application/json",
            },
            body: JSON.stringify({ decision_id: decisionId, changes }),
          },
        );
        let data;
        try {
          data = await response.json();
        } catch (parseError) {
          throw new Error("The confirmation returned an unreadable response.");
        }
        if (!response.ok || !data.ok) {
          throw new Error(data.error || "Could not confirm this item.");
        }
        window.location.reload();
      } catch (error) {
        showIssueError(card, error.message || "Could not confirm this item.");
        setBusy(card, false);
      }
    });

    skipToggle?.addEventListener("click", () => {
      if (!skipBox) return;
      skipBox.hidden = false;
      skipBox.querySelector("[data-skip-reason]")?.focus();
    });

    const submitSkip = async (reason) => {
      clearIssueError(card);
      setBusy(card, true);
      const decisionId = form.querySelector('[name="decision_id"]')?.value || "";
      try {
        const response = await fetch(
          `/tasks/${taskId}/normalize/issues/${card.dataset.issueId}/skip`,
          {
            method: "POST",
            headers: {
              Accept: "application/json",
              "Content-Type": "application/json",
            },
            body: JSON.stringify({ decision_id: decisionId, reason }),
          },
        );
        let data;
        try {
          data = await response.json();
        } catch (parseError) {
          throw new Error("The skip response was unreadable.");
        }
        if (!response.ok || !data.ok) {
          throw new Error(data.error || "Could not skip this item.");
        }
        window.location.reload();
      } catch (error) {
        showIssueError(card, error.message || "Could not skip this item.");
        setBusy(card, false);
      }
    };

    skipDirect?.addEventListener("click", () => {
      void submitSkip("");
    });

    skipButton?.addEventListener("click", () => {
      const reason = skipBox?.querySelector("[data-skip-reason]")?.value?.trim() || "";
      void submitSkip(reason);
    });
  });
}

// AI connection window. The header/page openers work as normal links without
// JavaScript; with JavaScript the connection test runs and a failure falls
// back to Offline Demo AI. The key is only ever held in the password input or
// the server-side encrypted store — never localStorage or IndexedDB.
const aiDialog = document.getElementById("ai-settings-dialog");
if (aiDialog) {
  const openers = document.querySelectorAll("[data-ai-settings-open]");
  const closeButton = aiDialog.querySelector("[data-ai-settings-close]");
  const form = document.getElementById("ai-settings-form-modal");
  const provider = document.getElementById("ai-provider");
  const model = document.getElementById("ai-model");
  const baseUrl = document.getElementById("ai-base-url");
  const apiKey = document.getElementById("ai-api-key");
  const keyStatus = document.getElementById("ai-key-status");
  const providerHint = document.getElementById("ai-provider-hint");
  const status = document.getElementById("ai-settings-status");
  const fallbackNotice = document.getElementById("ai-fallback-notice");
  const connectButton = document.getElementById("ai-connect");
  const offlineButton = document.getElementById("ai-use-offline");
  let savedKeyStatus = "No saved API key.";

  const setStatus = (message, kind = "") => {
    status.textContent = message;
    status.className = `small ai-settings-status${kind ? ` ${kind}` : ""}`;
  };
  const setFallback = (message) => {
    fallbackNotice.hidden = !message;
    fallbackNotice.textContent = message || "";
  };
  const keyStatusFor = (settings) => {
    if (!settings.key_configured) {
      return "No saved API key. A server environment key may still be used.";
    }
    if (settings.key_source === "environment") {
      return "Environment key available (value not displayed).";
    }
    return `Saved key: ${settings.key_hint || "••••"} (${settings.key_source})`;
  };
  const updatePageSummary = (settings) => {
    const badge = document.querySelector("[data-ai-summary-badge]");
    const text = document.querySelector("[data-ai-summary-text]");
    if (!badge || !text) return;
    const online = settings.provider === "openai" && settings.key_configured;
    badge.className = `badge ${online ? "badge-accepted" : "badge-state"}`;
    badge.textContent = online ? "OpenAI-compatible" : "Offline Demo AI";
    text.textContent = online
      ? `${settings.model || "model"} · key configured`
      : `Offline active · test ${settings.model || "deepseek-flash"} online`;
  };
  const syncProviderHint = () => {
    if (!providerHint) return;
    providerHint.textContent = provider.value === "offline"
      ? "Offline Demo AI uses local rules and needs no key or network. Select OpenAI-compatible to test a key."
      : "The key is encrypted only after a successful test. Connect probes the Base URL with a 5-second limit.";
  };
  const fill = (settings) => {
    provider.value = settings.provider || "offline";
    model.value = settings.model || "";
    baseUrl.value = settings.base_url || "";
    apiKey.value = "";
    savedKeyStatus = keyStatusFor(settings);
    keyStatus.textContent = savedKeyStatus;
    setFallback("");
    setStatus("");
    syncProviderHint();
    updatePageSummary(settings);
  };
  const load = async (preferOnline = false) => {
    try {
      const response = await fetch("/settings/ai", {
        headers: { Accept: "application/json" },
      });
      if (!response.ok) throw new Error("Could not load AI settings.");
      const settings = await response.json();
      fill(settings);
      if (preferOnline && settings.provider === "offline") {
        // A connection test is an online action by default. The active provider
        // only changes after a successful Connect; the page card still shows the
        // current active provider until then.
        provider.value = "openai";
        syncProviderHint();
        setStatus(
          "Offline Demo AI is currently active. Paste a key and Connect to test OpenAI-compatible; the active provider changes only after a successful test.",
          "is-pending",
        );
      }
    } catch (error) {
      setStatus(error.message || "Could not load AI settings.", "is-error");
    }
  };

  openers.forEach((opener) => {
    opener.addEventListener("click", (event) => {
      if (typeof aiDialog.showModal !== "function") return;
      event.preventDefault();
      fill({
        provider: "offline",
        model: "deepseek-flash",
        base_url: "https://api.deepseek.com",
        key_configured: false,
      });
      aiDialog.showModal();
      void load(opener.hasAttribute("data-ai-open-online"));
    });
  });
  closeButton?.addEventListener("click", () => aiDialog.close());
  aiDialog.addEventListener("click", (event) => {
    if (event.target === aiDialog) aiDialog.close();
  });
  provider?.addEventListener("change", syncProviderHint);
  apiKey?.addEventListener("input", () => {
    const value = apiKey.value.trim();
    if (value && provider.value === "offline") {
      // Pasting a key while Offline Demo AI is selected means the presenter
      // wants to test the online provider. Switch without hiding the intent.
      provider.value = "openai";
      syncProviderHint();
      setStatus("API key detected. OpenAI-compatible is selected for this test.", "is-pending");
    }
    if (!value) {
      keyStatus.textContent = savedKeyStatus;
      return;
    }
    keyStatus.textContent = `Key will be encrypted after a successful test · visible hint ••••${value.slice(-4)}`;
  });

  const connect = async (forceOffline = false) => {
    if (forceOffline) {
      provider.value = "offline";
    } else if (provider.value === "offline" && apiKey.value.trim()) {
      provider.value = "openai";
    }
    syncProviderHint();
    connectButton.disabled = true;
    offlineButton.disabled = true;
    setFallback("");
    setStatus("Testing connection… (maximum 5 seconds)", "is-pending");
    const formData = new FormData(form);
    if (forceOffline) formData.set("provider", "offline");
    const controller = new AbortController();
    const abortTimer = window.setTimeout(() => controller.abort(), 6000);
    try {
      const response = await fetch("/settings/ai/test", {
        method: "POST",
        headers: {
          Accept: "application/json",
          "Content-Type": "application/x-www-form-urlencoded",
        },
        body: new URLSearchParams(formData),
        signal: controller.signal,
      });
      let data;
      try {
        data = await response.json();
      } catch (parseError) {
        throw new Error("The connection test returned an unreadable response.");
      }
      if (!response.ok) {
        throw new Error(data.detail || data.message || "Could not test the connection.");
      }
      if (data.fallback) {
        // Auto-fallback keeps the presenter's attempted model/base values in
        // the form, clears only the secret, and changes the active provider to
        // offline. This prevents the panel from looking like a page refresh.
        provider.value = "offline";
        syncProviderHint();
        apiKey.value = "";
        savedKeyStatus = keyStatusFor(data.settings);
        keyStatus.textContent = savedKeyStatus;
        updatePageSummary(data.settings);
        if (data.connected) {
          setStatus(data.message, "is-warning");
        } else {
          const action = data.action ? ` ${data.action}` : "";
          setStatus(`${data.message}${action}`, "is-error");
        }
        setFallback(
          `Offline Demo AI active · ${data.model || "grounded-rules-v1"}. You can close this window and start cleaning.`,
        );
      } else if (data.connected) {
        if (data.provider === "offline") {
          // An intentional offline choice does not need to reset the form.
          // Only clear the secret; keep model/base values the presenter typed.
          apiKey.value = "";
          savedKeyStatus = keyStatusFor(data.settings);
          keyStatus.textContent = savedKeyStatus;
          updatePageSummary(data.settings);
          setStatus(`Offline Demo AI ready · ${data.model} · 0 ms`, "is-ok");
        } else {
          fill(data.settings);
          const latency = Number(data.latency_ms || 0);
          setStatus(`Connected · ${data.model} · ${latency} ms`, "is-ok");
        }
      } else {
        const action = data.action ? ` ${data.action}` : "";
        setStatus(`${data.message}${action}`, "is-error");
      }
    } catch (error) {
      const message = error?.name === "AbortError"
        ? "The connection test timed out after 6 seconds."
        : (error.message || "Could not test the connection.");
      setStatus(message, "is-error");
      setFallback(
        "You can keep working with Offline Demo AI. The cleanup does not require a network.",
      );
    } finally {
      window.clearTimeout(abortTimer);
      connectButton.disabled = false;
      offlineButton.disabled = false;
    }
  };

  form?.addEventListener("submit", (event) => {
    event.preventDefault();
    void connect(false);
  });
  offlineButton?.addEventListener("click", () => {
    void connect(true);
  });
}
