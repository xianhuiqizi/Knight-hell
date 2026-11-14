# Demo Day Phase C — AI connection

Baseline restored to **phase 1** (`5f59599`) before this increment. The previous
C/D attempt is preserved outside the branch at `backup/phase-cd-attempt`
(`a907caf`) but is not used as the starting point.

## Delivered

- Visible **AI connection** entry:
  - header button;
  - card on every cleanup task page;
  - full settings page opens the same dialog.
- Provider choices: **OpenAI-compatible** and **Offline Demo AI**.
- Default online target: **DeepSeek Flash** — model `deepseek-flash`, base URL
  `https://api.deepseek.com`.
- Fields: model, base URL, API key (`type=password`), key hint (`••••ABCD`) and
  a live **Connect** action.
- `POST /settings/ai/test` tests and saves in one action. The connection budget
  is hard-capped: the probe uses a 5.0-second HTTP timeout and the endpoint has a
  5.2-second watchdog, so the browser receives a result within 5 seconds.
- Success returns `model`, `latency_ms`, provider and saved key hint.
- Failures classify as `invalid_key`, `quota`, `network`, `model_or_url`,
  `config` or `provider_error`, with a plain-English next action.
- No key supplied or test failure:
  - the server automatically switches the user to Offline Demo AI;
  - a yellow notice is shown;
  - the cleanup task can still be started and completed;
  - a previously saved key is retained for a later retry.
- Successful keys are encrypted by the existing `AISettingCipher`; the key is
  never returned to the browser, logged, or written to `localStorage`/IndexedDB.
- `FLOWREMOTE_DEMO_MODE=1` pre-fills safe fields from `FLOWREMOTE_AI_PROVIDER`,
  `FLOWREMOTE_AI_MODEL`, `FLOWREMOTE_AI_BASE_URL`/`OPENAI_BASE_URL`. The key is
  shown only as configured/not configured; the presenter still pastes and clicks
  Connect.
- Cleaning remains rules-only. AI connectivity is an explicit, optional step and
  never blocks normalization.

## Endpoint contract

`POST /settings/ai/test` (signed-in user, form or JSON):

```json
{
  "ok": true,
  "connected": true,
  "fallback": false,
  "provider": "openai",
  "model": "deepseek-flash",
  "latency_ms": 184,
  "error_code": null,
  "message": "Connected. The model is available.",
  "action": "",
  "attempted_model": null,
  "key_source": "submitted",
  "demo_mode": false,
  "settings": {
    "provider": "openai",
    "model": "deepseek-flash",
    "base_url": "https://api.deepseek.com",
    "key_configured": true,
    "key_hint": "••••ABCD",
    "key_source": "saved"
  }
}
```

A failed test remains HTTP 200 so the browser can render the fallback; it returns
`ok: false`, `fallback: true`, `provider: "offline"`, an `error_code`, and the
same safe settings object. No key material is included.

## Security properties

- API key input is never prefilled by the server; only the last four characters
  are returned as a hint.
- On success the encrypted value is written to `ai_settings`; on failure the
  submitted value is dropped.
- No activity, AI suggestion or usage row is written by a connection test.
- The browser JavaScript does not use `localStorage` or IndexedDB for the AI key.
- Connection probes use `httpx` directly and never include a request body in
  errors or logs.

## Verification

```text
pytest tests -q
# at Phase C close: 298 passed, 11 subtests passed
# after Phase D: 313 passed, 11 subtests passed
```

New tests: **26**
- 14 unit tests for probe result mapping, timeouts, URL normalization, model
  listing, key non-disclosure and browser-storage avoidance.
- 11 HTTP/DB tests for sign-in protection, the DeepSeek Flash default target,
  success, encryption, existing-key reuse, invalid-key and network fallback,
  no-key fallback, environment prefill, settings controls and no task/activity
  writes; quota mapping is covered at the unit level.
- 1 cleanup-page test proving the visible AI connection entry.

A real loopback probe against a temporary local OpenAI-compatible server was
also exercised:
- valid key → `openai`, `local-demo-model`, ~0.7 s;
- invalid key → `invalid_key` with automatic `offline` fallback, ~0.7 s.

Screenshots: `output/phase-c/`
- `01-ai-connection-form.jpg` — form with key masked and `••••ABCD` hint;
- `02-ai-connected.jpg` — connected model and 1422 ms latency;
- `03-page-ai-connected.jpg` — page summary updated to OpenAI-compatible;
- `04-invalid-key-fallback.jpg` — invalid key, yellow Offline Demo AI notice.

## Not in this increment

- Phase D was not part of this increment. It is now implemented separately:
  editable cards, AI suggestion, revalidation, skip export and the finish/download
  gate are documented in `docs/demoday-phase-d-report.md`.
- No real external AI key was used in automated tests. The probe path is covered
  by mocked transports and a local compatible HTTP server.

## Rollback

C changes are code-only; there is no new migration. To return to phase 1:

```powershell
git restore -- src/flowremote/api/app.py `
  src/flowremote/control_plane/ai_settings.py `
  src/flowremote/api/routes/ai_settings.py `
  src/flowremote/ui/templates/base.html `
  src/flowremote/ui/templates/ai_settings.html `
  src/flowremote/ui/templates/normalize_task.html `
  src/flowremote/ui/static/app.css `
  src/flowremote/ui/static/app.js `
  src/flowremote/ui/static/sw.js `
  src/flowremote/api/routes/normalization.py `
  src/flowremote/devtools/seed_demoday.py `
  README.md pyproject.toml uv.lock .env.example
Remove-Item src/flowremote/agent/connection.py `
  tests/unit/test_ai_connection.py `
  tests/integration/test_ai_connection.py `
  docs/demoday-phase-c-report.md
```

Then reset the local database with the phase-1 seed if desired. The existing
`/settings/ai` route and encrypted table remain valid either way.
