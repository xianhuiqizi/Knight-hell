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
