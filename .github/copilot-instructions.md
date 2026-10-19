# RV Control Web steering

- Build the application described in `docs/architecture.md`; use Python for the backend and Svelte for the frontend. RV-Control is an MQTT publisher only; never import its code or configuration.
- Be pragmatic and concise. Change the smallest relevant surface; avoid speculative work, repeated analysis, and wasteful tool use.
- Run focused checks for changed behavior. Do not repeat checks or run unrelated suites without a reason.
- Leave Git work (staging, commits, branches, Git tags, and pushes) to the user. Do not run Git commands or spend time on Git status, diffs, or repository housekeeping unless explicitly requested.
- Use `deploy/docker-image.sh` for every Docker image build, tag, or push, whether invoked by a person or automation. Keep credentials out of tracked files.
- The first release is read-only: no MQTT publish or control path from the UI.

## Existing implementation patterns

- Read the relevant implementation and linked documentation before changing behavior. Reuse existing components, helpers, naming, and styling rather than introducing parallel patterns.
- Frontend conventions and the shared notification API are documented in [Frontend design](../docs/architecture.md#13-frontend-design-detail). Use `notify()` from `frontend/src/notifications.js` for transient results and errors; do not add inline result messages, widget-local toast systems, or separate dismissal timers.
- Keep `Notifications.svelte` mounted once at application level, outside the tab tree and login form. Preserve its five-second lifetime, rounded theme-aware styling, accessible announcements, and manual dismissal.
- Keep live telemetry and stale/missing/invalid indicators in widgets. Pending/busy state is separate from notification lifetime; dismissing a notification must not enable controls or imply physical-state confirmation.
- Follow the existing frontend browser regression pattern in `frontend/tests/`; use mocked HTTP/WebSocket responses for action tests, never a real Coach controller. See [notification testing](../docs/dashboard-testing.md#notifications).
- Update the relevant architecture section, feature/testing guide, and unreleased changelog when behavior or reusable patterns change. Keep README links current; avoid duplicating implementation details across documents.