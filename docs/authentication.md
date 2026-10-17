# Viewer login

The application supports one to three named accounts with identical access to
the configured dashboard and Coach actions. There are no roles, registration,
password-reset emails, or account-management screens. Configuration and
password hashes live outside the image; they are loaded at backend startup.

For preparing the full external configuration directory and bringing up
production with Docker Compose, follow the
[deployment runbook](deployment.md). It also documents the localhost UI-only
Compose workflow. Account setup below applies to both.

## Set up accounts

### Recommended: create the file interactively

The setup helper creates the YAML file for you. It asks for a username, a
hidden password, and confirmation. Press Enter at the next username prompt
to finish, or create up to three accounts. Only hashes are saved, with file
permissions `0600`. It refuses to overwrite an existing file or symlink and
requires a terminal so passwords are never echoed.

With the Docker image, no local Python installation is required. First
build an updated image using the project's build script:

```sh
bash deploy/docker-image.sh build
```

Then create your external configuration directory and run the helper:

```sh
mkdir -p "$HOME/rv-control-web-config"
docker run --rm -it --network none \
  --user "$(id -u):$(id -g)" \
  --mount type=bind,source="$HOME/rv-control-web-config",target=/config \
  docker.io/triphoop/rv-control-web:latest \
  python -m backend.app.setup_accounts --output /config/auth-users.yaml
```

This overrides the normal server command for a one-off setup container. The
directory is writable only during setup; keep the application's normal
configuration mount read-only. Running under your UID/GID gives you ownership
of the resulting host file. This command performs no network operations.
Use the appropriate architecture-specific image tag if you built with one.

Or run locally from the repository root:

```sh
mkdir -p "$HOME/rv-control-web-config"
backend/.venv/bin/python -m backend.app.setup_accounts \
  --output "$HOME/rv-control-web-config/auth-users.yaml"
```

Your file is now ready; continue with **Runtime configuration** below. Set
`auth.credentials_file: ./auth-users.yaml` in the runtime config located in
that same directory and set the browser origins. The helper does not edit
runtime settings or enable authentication automatically.

For later credential changes, use the hash-only helper below or create a new
credential file under a different output name, inspect it, and deliberately
replace the old file before restarting. Setup never silently replaces accounts.

### Alternative: generate hashes and write YAML manually

Install backend requirements as described in the [README](../README.md).
From the repository root, generate a hash interactively for each password:

```sh
backend/.venv/bin/python -m backend.app.password_hash
```

The helper asks for and confirms a 12-1024-character password without echoing
it. It prints a salted scrypt hash. Passwords are never command-line arguments.
The hash format uses scrypt with N=32768, r=8, p=1, a random 16-byte salt,
and a 64-byte output.

Create `auth-users.yaml` beside your external runtime `config.yaml`:

```yaml
users:
  - username: bruce
    password_hash: "PASTE_GENERATED_HASH_HERE"
```

The placeholder is deliberately not a usable hash. Add at most two more users
with their own generated hashes. Usernames are unique, case-sensitive, and
1-64 characters without leading/trailing whitespace. Restrict the file to its
owner (`chmod 600 /path/to/auth-users.yaml`) and keep it out of source control.
The repository ignores files named `auth-users.yaml`; if using another name,
store it outside the repository.

## Runtime configuration

For HTTPS through Traefik:

```yaml
auth:
  credentials_file: ./auth-users.yaml
  origins:
    - https://your-rv-domain.example
  secure_cookie: true
```

Replace the domain with the actual browser origin. `credentials_file` resolves
relative to the runtime config directory. The existing read-only `/config`
mount can include the credential file; no credentials belong in the image or
Compose labels. Keep file ownership compatible with the container's user.

For local HTTP development:

```yaml
auth:
  credentials_file: ./auth-users.yaml
  origins:
    - http://127.0.0.1:5173
    - http://127.0.0.1:8000
  secure_cookie: false
```

Origins are exact `scheme://host[:port]` values with no path, trailing slash,
wildcard, credentials, query, or fragment. Add `localhost` separately if that
is what you use in the browser. Vite proxies `/api` and `/ws`, so allow the
browser's Vite origin, not just the backend origin.

Secure cookies default to true and require HTTPS origins. Insecure cookies
are allowed only for HTTP loopback origins (`127.0.0.1`, `localhost`, or
`[::1]`). For LAN use, serve HTTPS through Traefik rather than disabling cookie
security. The application does not derive trusted origins from forwarded
headers; set them explicitly.

Authentication defaults to enabled. Missing credentials, invalid hashes, no
allowed origins, duplicate usernames, or more than three users abort startup.
There is no silent anonymous fallback.

The [fake-data test configuration](../config.test.yaml) explicitly contains
`auth.enabled: false`. This preserves the anonymous local testing workflow and
logs a warning at startup. Do not use that setting for a deployed application.
When authentication is disabled and MQTT commands are enabled, any viewer who
can reach the application can use configured controls. Restrict this combination
to an isolated local test network.
To test login locally, copy the test configuration to a local file, replace its
disabled `auth` section with the loopback example above, create credentials,
and start the backend with `RV_WEB_CONFIG` pointing to that file.

## Browser behavior

An unauthenticated viewer sees a username/password login form. After successful
login, the browser loads dashboard configuration and connects to the live
WebSocket. The header shows the account name and a Logout button.

- Sessions have an absolute eight-hour lifetime, not a sliding timeout.
- Tokens are random, stored only in backend memory, and transported in a
  host-only `rv_web_session` cookie with `HttpOnly`, `SameSite=Strict`, path `/`,
  and `Secure` for HTTPS configurations.
- Tokens are not returned in JSON or stored in browser local storage.
- Logout deletes the cookie, revokes the token, and closes that session's live
  WebSockets. Other independent sessions are unaffected.
- Logging in with an existing session cookie rotates that token.
- Expiry closes idle WebSockets as well as active ones; outgoing telemetry
  checks session validity before sending.
- A backend restart drops all sessions and logs everyone out. The UI returns
  to login after it detects the lost session.

Use one backend process/Uvicorn worker. Multiple workers would have separate
session stores and are not supported. Up to 256 sessions are retained; expired
sessions are removed and the oldest session is evicted if the cap is reached.

## Protected surfaces and request checks

Dashboard `/api/*`, widget `/assets/*`, and `/healthz` require a valid session.
WebSocket upgrades require both a valid session and an allowed Origin.
Login and logout also require an allowed Origin, protecting those
cookie-authenticated actions against cross-origin requests.

The login page and compiled frontend shell under `/ui-assets` remain public so users can log in;
they contain no dashboard configuration or credentials. `/api/auth/session`
is public and reports whether authentication is enabled and whether the
current cookie is authenticated. It does not expose other accounts or sessions.
Interactive API docs and OpenAPI output are disabled. HTTP responses use
`Cache-Control: no-store`.

Login errors use the same message for unknown usernames and incorrect
passwords. Password hashing runs off the event loop with at most two concurrent
checks. Login submissions, including successful ones, are limited to five per
client address per minute and thirty globally per minute. A limit response is
HTTP 429 with `Retry-After: 60`. Limits are in memory and reset on restart.
Behind a proxy, multiple viewers may share an address bucket; the global
limit also applies. Do not configure broad trust of forwarded IP headers
merely to change throttling behavior.

## Changing credentials

Edit the external credential file and restart the backend. This applies account
additions/removals and password changes and invalidates every existing session.
There is no in-app reset path. Keep a protected backup of credentials if you
need recovery; do not log plaintext passwords or commit hashes.

## Troubleshooting and tests

| Symptom | Check |
| --- | --- |
| Startup rejects configuration | Credentials exist, generated hashes are valid, origins match cookie security, account count is 1-3 |
| Login/logout returns 403 | Browser origin matches `auth.origins` exactly, including scheme and port |
| Login works but session is missing | HTTPS is used for Secure cookies; browser accepts cookies; frontend and API are same-origin |
| WebSocket is rejected | Valid cookie, allowed Origin, and proxy WebSocket forwarding |
| `/healthz` returns 401 | Expected without a session; use an authenticated request instead of anonymous probes |
| Too many login attempts | Wait a minute; avoid repeated scripted attempts |
| Logged out after backend restart | Expected in-memory-session behavior |
| No login form in fake-data setup | `auth.enabled: false` is intentionally set in `config.test.yaml` |

Install test dependencies and run focused verification:

```sh
backend/.venv/bin/pip install -r backend/requirements-test.txt
backend/.venv/bin/python -m unittest backend.tests.test_auth -v
```

Tests cover password hashing, invalid settings, cookie flags, anonymous
rejection, authenticated HTTP/WebSocket access, origin checks, throttling,
rotation, logout revocation, and expiry without incoming telemetry.
Authentication does not introduce MQTT control or publish capabilities.
