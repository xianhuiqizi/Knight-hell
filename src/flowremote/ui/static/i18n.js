/* Translate text inserted after the server-rendered page (AI advice, sync
   badges, progress labels, validation errors). English is the default; this file
   does nothing unless the server set the Chinese language cookie. */
(() => {
  const lang = window.FLOWREMOTE_LANG || "en";
  if (lang !== "zh") return;
  const dictionary = window.FLOWREMOTE_I18N || {};
  const patterns = (window.FLOWREMOTE_I18N_PATTERNS || []).map(([pattern, replacement]) => [
    new RegExp(pattern, "g"),
    replacement.replace(/\\(\d+)/g, "$$$1"),
  ]);
  const singleWordExclude = new Set([
    "row", "rows", "test", "online", "box", "kg", "piece", "available",
    "operator", "admin", "saved", "none", "ready", "human", "records", "files",
    "tasks", "task", "status", "open", "save", "back", "close", "cancel", "field",
    "fields", "file", "format", "sheet", "header", "method", "duration", "input",
    "output", "success", "failures", "flagged", "passed", "skipped", "approved",
    "written", "synced", "failed", "running", "uploaded", "validating", "executing",
    "partial", "normalized", "mapped", "detected", "complete", "confirmed",
    "unresolved", "review", "approval", "password", "name", "model", "provider",
    "settings", "download", "upload", "start", "skip", "confirm", "edit", "accept",
    "blocked", "proceed", "enabled", "disabled", "owner", "result", "results",
    "event", "events", "log", "actor", "true", "false", "local", "http", "excel",
  ]);
  const keys = Object.keys(dictionary).filter(
    (key) => key.length >= 3 && !(singleWordExclude.has(key.toLowerCase()) && !key.includes(" ")),
  );
  keys.sort((a, b) => b.length - a.length);
  const escape = (value) => value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const phraseRe = keys.length
    ? new RegExp(`(?<![A-Za-z0-9])(${keys.map(escape).join("|")})(?![A-Za-z0-9])`, "g")
    : null;
  const skipSelector =
    "script,style,pre,code,.mono,.task-id,.task-file,.log-time,.log-actor," +
    ".issue-values dd,[data-i18n-skip]";

  const translate = (value) => {
    if (!value) return value;
    const leading = value.slice(0, value.length - value.trimStart().length);
    const trailing = value.slice(value.trimEnd().length);
    const core = value.trim().replace(/\\s+/g, " ");
    if (!core) return value;
    if (dictionary[core]) return leading + dictionary[core] + trailing;
    let translated = core;
    for (const [pattern, replacement] of patterns) {
      translated = translated.replace(pattern, replacement);
    }
    if (phraseRe) translated = translated.replace(phraseRe, (match) => dictionary[match] || match);
    return leading + translated + trailing;
  };

  const parentIsSkipped = (node) => {
    const element = node.nodeType === Node.ELEMENT_NODE ? node : node.parentElement;
    return !element || !element.closest(skipSelector);
  };

  const translateAttributes = (element) => {
    if (!element || element.nodeType !== Node.ELEMENT_NODE) return;
    for (const name of ["placeholder", "aria-label", "title", "alt"]) {
      const value = element.getAttribute(name);
      if (value) {
        const next = translate(value);
        if (next !== value) element.setAttribute(name, next);
      }
    }
  };

  const translateTextNode = (node) => {
    if (!node || node.nodeType !== Node.TEXT_NODE) return;
    if (!parentIsSkipped(node)) return;
    const next = translate(node.nodeValue);
    if (next !== node.nodeValue) node.nodeValue = next;
  };

  const walk = (root) => {
    if (!root) return;
    if (root.nodeType === Node.TEXT_NODE) {
      translateTextNode(root);
      return;
    }
    if (root.nodeType !== Node.ELEMENT_NODE && root.nodeType !== Node.DOCUMENT_FRAGMENT_NODE) return;
    if (root.nodeType === Node.ELEMENT_NODE) translateAttributes(root);
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT | NodeFilter.SHOW_ELEMENT);
    let current = walker.nextNode();
    while (current) {
      if (current.nodeType === Node.TEXT_NODE) translateTextNode(current);
      else translateAttributes(current);
      current = walker.nextNode();
    }
  };

  const start = () => {
    // The server already translated the initial HTML. Only observe content
    // inserted later (AI advice, sync badges, progress labels, validation).
    const observer = new MutationObserver((mutations) => {
      for (const mutation of mutations) {
        if (mutation.type === "characterData") {
          translateTextNode(mutation.target);
        } else {
          for (const node of mutation.addedNodes) walk(node);
        }
      }
    });
    observer.observe(document.body, {
      childList: true,
      subtree: true,
      characterData: true,
    });
  };

  if (document.body) start();
  else document.addEventListener("DOMContentLoaded", start, { once: true });
})();
