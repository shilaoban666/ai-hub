# fancyqube embedded assistant trial

## Local trial

- AI Hub frontend: http://localhost:15173/embed/chat
- fancyqube: http://localhost:10925/index/
- Open an authenticated xadmin business page and click the bottom-right AI button.
- Users already signed in to fancyqube can sign into the assistant through a registered confidential client: the business backend exchanges its client credentials and the current IAM user ID for a user token. The host passes the token to the iframe, which keeps it in memory. No login popup is opened. See [embedded SSO setup](embed-sso.md).
- Closing the drawer hides the iframe without destroying it. Full business-page navigation still reloads the iframe; this version does not add background-run recovery.

The trial uses the existing gateway, IAM and AI Hub backend. It does not mock model responses. Browser tests use isolated test responses, which are not served to users.

## Integration

fancyqube's `xadmin/base.html` uses the `aihub_assistant_url` template tag to load AI Hub's `/embed/assistant.js`. Configure `AIHUB_EMBED_URL` at the bottom of `Project/settings.py` with a complete URL, for example `http://localhost:15173/embed/chat` locally or `https://aihub.example.com/embed/chat` in production. An empty URL hides the entry on every operating system; no host or port is inferred from the business page. `AIHUB_EMBED_DEPARTMENT` controls the department whose active members see the entry. `AIHUB_EMBED_ALLOWED_NAMES` is an additional list of employee names matched exactly against the account's `first_name`; these employees can see the entry without department membership. Both paths require an authenticated, active account. Restart fancyqube after changing these settings.

For deployment, configure `VITE_EMBED_PARENT_ORIGINS` with exact allowed host origins before building AI Hub. Vite development defaults include `VITE_ONLINE_TARGET`, `http://localhost:10925` and `http://127.0.0.1:10925`. Same-origin hosts are also accepted. Configure the gateway's CSP `frame-ancestors` for those hosts, remove conflicting frame denial headers only on the trusted embed route, and allow its origin in the host's `frame-src`/`script-src` policies.

Pages outside the xadmin base template require the same script entry. Multiple levels of business iframes and cross-origin business frames may need additional active-page forwarding. Embedded AI-generated HTML is shown as source in this trial.

## Page context

The host and iframe use `postMessage` with protocol `aihub-embed-v1`. Both check origin and source; the iframe uses an explicit origin allowlist. The host sends URL and title when the assistant is ready and when page context changes. Same-origin business subframes report their URL after user interaction.

Each chat request has optional `page_context: { url, title }`. The user can turn this off. Only the query parameters `id`, `page_id`, `function_id`, `global_function_id` and `tab` survive; hash routes retain their path. Arbitrary query values and URL credentials are excluded. The server validates again, passes the result to the runtime as untrusted reference data and stores it in the run's configuration snapshot. It does not fetch the URL or treat it as authorization. Existing user messages and session titles remain unchanged.

Skills and MCPs continue to come from the user's existing assistant. GitLab access and business interpretation are outside this integration change.

## Verification

- `node --test tests/embed-context.test.mjs`
- `node browser-tests/embed-chat.mjs` (set `PLAYWRIGHT_MODULE_PATH` when Playwright is external)
- `python -m unittest test_embed_context` with an isolated test database
- `python test_agent_service.py` with an isolated test database
- `npm run build`

The browser check covers login-state changes, page context, secret query removal, message payloads, streaming while collapsed, session navigation, desktop/mobile layout and context opt-out. A real model response requires an eligible fancyqube session and a configured IAM bridge.
