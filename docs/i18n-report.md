# Bilingual UI report — English / 中文

Status: **implemented and verified** on 2026-11-14.

## 1. Default behaviour

English is the default for every new visitor. The server does **not** infer the
language from `Accept-Language`; a browser with `zh-CN` still opens in English.
The choice is opt-in through the top-bar switch.

```text
No cookie                         -> English
flowremote_lang=zh                -> Chinese
flowremote_lang=en                -> English
```

The switch is available on authenticated and unauthenticated pages:

```text
GET  /language/zh?next=/tasks/TASK-...
GET  /language/en?next=/tasks/TASK-...
POST /language/{en|zh}             (no-JavaScript fallback)
```

`next` must be a same-site path; external/`//host` targets fall back to `/`.
The cookie is `flowremote_lang`, valid for one year, `SameSite=Lax`, path `/`.

## 2. Rendering architecture

- `src/flowremote/ui/i18n.py` owns the English→Chinese phrase map, numeric
  patterns and the HTML translator.
- `api/rendering.py` detects the cookie, sets `<html lang>`, passes the map to the
  browser, and translates the rendered HTML for `zh`.
- `ui/static/i18n.js` uses the same dictionary with a `MutationObserver` to
  translate dynamic content added by app JavaScript: AI advice labels, progress
  states, review counters and validation messages.
- `<script>`, `<style>`, `<pre>`, `<code>` and `data-i18n-skip` regions are
  protected. AI-generated reasons/evidence are marked `data-i18n-skip` and stay
  in the model's original language rather than being machine-mangled.
- Single generic words such as `row`, `box` or `piece` are translated only when
  they are a whole text node, preventing partial replacement inside generated
  English explanations.

## 3. Covered surfaces

| Surface | English default | Chinese |
| --- | --- | --- |
| Header, user menu, language switch | Yes | Yes |
| Login, signup | Yes | Yes |
| Task list and new task | Yes | Yes |
| Normalization progress, summary, review cards, AI advice, finish gate | Yes | Yes |
| AI connection dialog, AI settings | Yes | Yes |
| Settings / onboarding / approval / execution / results | Yes | Yes |
| Demo landing | Yes | Yes |
| Server status labels and page titles | Yes | Yes |
| Dynamic JavaScript labels/errors | Yes | Mostly, with technical fallback |

Technical values (names, IDs, model names, file names, generated AI reasoning and
evidence) are intentionally not translated.

## 4. Verification

Automated suite:

```text
321 passed, 11 subtests passed
```

Six HTTP tests in `tests/integration/test_i18n.py` cover:

1. default English even with `Accept-Language: zh-CN`;
2. switch to Chinese sets the cookie and translates the login page;
3. switch back to English;
4. invalid language returns 404 and external `next` is rejected;
5. authenticated home/settings pages translate;
6. the client translator asset is served with the current cache version.

A real headless Edge session also verified:

- `/login` opens with `<html lang="en">` and **Work email** / **Log in**;
- clicking **中文** sets the cookie, reloads, and shows **工作邮箱** / **登录**;
- the task review page shows **人工复核**, translated cards and the AI advice
  label;
- clicking **AI suggestion** inserts a **离线演示 AI** result through the client
  translator;
- switching back to **EN** restores **Human review** and the English UI.

Artifacts:

- `output/phase-d/i18n-en-login.png`
- `output/phase-d/i18n-zh-login.png`
- `output/phase-d/i18n-zh-review.png`
- `output/phase-d/i18n-en-review.png`
- `output/phase-d/i18n-browser-verification.json`

A final **real mouse** GUI run used an isolated database on port `8011`:

```text
demo login → New task → choose six files → Upload & detect
→ Start cleaning → 6 × AI suggestion → 6 × Confirm → Complete cleaning
→ Download cleaned .xlsx → inspect workbook → switch to 中文 → back to EN
```

Result: 6 files, 174 source rows, 36 records, 6 confirmed, 0 skipped,
`normalized/changes/unresolved` = 37/238/1 rows including headers, all 36
records arithmetically valid. The Chinese pass exposed one mixed sentence
(`Cleaning complete. 36 ... are ready to download.`); it was fixed and the suite
re-run at **321 passed**. Evidence: `output/phase-d/gui-test-normalized.xlsx`
and `output/phase-d/gui-test-verification.json`.

## 5. Cache and service worker

The asset version is `20261118r`. `i18n.js` is part of the service-worker shell
and the cache name is `flowremote-shell-20261118r`, so an old cached bundle does
not hide the switch.

## 6. Limitations

- AI-generated review reasons/evidence remain in the language returned by the
  model. The surrounding human UI is translated.
- Server validation messages returned as JSON are English; the browser
  translator covers the common messages and the fields remain usable.
- The static marketing site outside the Jinja app shell is not part of this
  switch; the Demo Day entry and all application pages are covered.
