# Changelog

Notable application, tooling, and deployment changes are recorded here.
Changes below are unreleased; no release version or Git tag has been assigned.

## Unreleased

### Added

- Automotive analog dial widgets with radial major and minor tick subdivisions,
  redline warning zones, tapered needle pointers with center hub caps, and
  calibrated scales for engine speed (`×1000 RPM`), vehicle speed (`MPH`),
  temperatures (`°F`), and boost pressure (`PSI`).
- `flow` layout container that arranges child widgets along a row respecting
  their configured `min_width` and cleanly breaks to subsequent lines without
  flex-stretching remaining widgets.
- Day / Night / Auto theme modes with masthead toggle, defaulting to Auto with
  system `prefers-color-scheme: dark` detection and `localStorage` persistence.
- Dark instrument cluster palette for Night mode with high-contrast dial
  graduations, luminous needle pointers, and dark pod styling.
- Full-screen/tab-occupying map widget centered on live GPS coordinates
  from an MQTT telemetry topic (such as `rv/gpsd/TPV`), supporting optional
  heading/compass direction, altitude, speed, GPS fix quality indicators,
  zoom controls, and orientation modes (`north_up` or `heading_up`).
- Dedicated GPS dashboard tab displaying the map widget across the entire tab view.
- Viewer login for one to three externally configured accounts with identical
  read-only access, salted scrypt password hashes, and a Logout button.
- Eight-hour, in-memory sessions using random HttpOnly, SameSite=Strict
  cookies, with Secure cookies for HTTPS deployments.
- Authentication for dashboard API, widget assets, health details, and
  WebSocket connections; origin checks for login, logout, and WebSockets.
- Login throttling, bounded concurrent password verification, generic invalid
  credential responses, and session revocation on logout, expiry, or restart.
- Interactive password-hash generation and an account setup command that
  creates external credential YAML with owner-only permissions, hidden
  password prompts, and overwrite protection. Both run from the Docker image.
- Offline dashboard checking against sample MQTT payloads, including topic
  coverage, nested paths and array indices, numeric values, and derived results.
- Read-only derived numeric widgets supporting `sum`, `difference`, `product`,
  `ratio`, and `average`; input topics participate in normal tab subscriptions.
- Configurable browser-only sparkline point limits and sampling intervals,
  based on backend receive timestamps.
- Isolated, localhost-only Mosquitto test deployment and a configurable fake
  telemetry publisher independent of RV-Control.
- Dashboard-driven fake topic selection, nested payload templates, static
  values, sine/ramp/sequence generators, and per-topic intervals, QoS, and
  retention. Offline scenario checking prints initial sample payloads.
- Explicit anonymous local test configuration and sample telemetry scenarios
  covering Renogy, Hughes, and WLED payloads.
- Shore Power example tab with voltage, current, power trend, error code,
  and energy readings alongside the Power tab.
- VS Code tasks for running the test backend and frontend.
- Backend tests for authentication, WebSocket/session lifecycle, sample
  validation, derived configuration, synthetic telemetry, scheduling, and
  credential setup; separate test dependency requirements.
- Detailed guides for [authentication](docs/authentication.md),
  [dashboard features and local testing](docs/dashboard-testing.md), and
  [production Docker Compose deployment](docs/deployment.md).

### Changed

- Authentication is enabled by default and fails startup on missing or invalid
  credentials/origins. Anonymous access now requires explicit
  `auth.enabled: false`, intended only for local tests.
- Deployment configuration examples include external credential paths and
  appropriate HTTPS or loopback-only cookie/origin settings.
- Production Compose connects to an existing broker through the host gateway
  rather than managing a broker. Runtime configuration and credentials remain
  outside the image, mounted read-only.
- Docker image builds use Docker's native/default platform unless
  `RV_WEB_PLATFORM` is set explicitly.
- Default image for build and push is
  `docker.io/triphoop/rv-control-web:latest`; image arguments remain optional
  overrides, while tagging requires explicit source and destination.
- Deployment guidance recommends native AMD64 and Raspberry Pi builds with
  separate architecture-specific tags, avoiding accidental tag overwrites.
- Compiled frontend assets moved to `/ui-assets` so the public login shell can
  load separately from protected widget images under `/assets`.
- HTTP responses use `Cache-Control: no-store`; interactive API documentation
  and OpenAPI endpoints are disabled.
- Frontend session discovery precedes dashboard loading; expired/revoked
  sessions return viewers to login instead of endlessly reconnecting.
- README and architecture documentation now describe implemented features,
  setup/restart workflows, production Compose, and current limitations.

### Fixed

- Invalid dashboard node types and non-finite or incorrectly typed chart
  bounds now produce explicit configuration errors.
- Sparkline sampling no longer treats unrelated chart updates as new readings.
- Shared sample-checker product evaluation imports its required math helper.
- WebSocket send failures are logged and caught by specific exception types
  rather than a broad exception handler.
- Invalid login input responses do not echo submitted password values.
- Protected widget assets no longer prevent the compiled login page loading.

### Removed

- Production Compose's bundled Mosquitto service, associated dependency, and
  production broker configuration. The separate test broker remains available.

### Upgrade notes

- Before deploying the updated application, create `auth-users.yaml` in the
  external configuration directory and configure allowed browser origins.
  Existing configurations without authentication settings will not start.
  See the [account setup instructions](docs/authentication.md).
- Production must use HTTPS with Secure cookies. HTTP cookies are restricted
  to configured loopback origins; do not deploy the anonymous test config.
- `/healthz` now requires a session when authentication is enabled. Update
  anonymous monitoring assumptions accordingly.
- Run one backend worker: sessions and telemetry caches are process-local.
  Backend restarts intentionally log out all viewers.
- Ensure an existing MQTT broker is reachable from the container; the
  production Compose stack no longer starts one.
- Match Compose's configured platform and image tag to the host. The build
  script's native default does not change Compose's ARM64 default.
- Rebuild images to include login assets and credential setup tools.
- Sparkline history remains browser-only and nonpersistent. No database,
  role-based authorization, registration, or MQTT UI control path was added.
