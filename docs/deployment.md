# Docker deployment runbook

Production uses Docker Compose with Traefik for HTTPS and the application
backend serving the built Svelte UI. The production stack does **not** run an
MQTT broker. It connects to an existing broker independently of RV-Control.

Run commands from the repository root unless noted otherwise. Docker and
Compose are required; Python and Node.js are not required on a deployment host
when using an already-built image.

## 1. Select or build an image

Use an image matching the deployment host:

| Host | Compose platform | Example image tag |
| --- | --- | --- |
| 64-bit Raspberry Pi OS | `linux/arm64` | `docker.io/triphoop/rv-control-web:latest-arm64` |
| Intel/AMD Linux | `linux/amd64` | `docker.io/triphoop/rv-control-web:latest-amd64` |

Prefer native builds on each host rather than configuring emulation:

```sh
# On the 64-bit Pi:
bash deploy/docker-image.sh build docker.io/triphoop/rv-control-web:latest-arm64

# On an AMD64 host:
bash deploy/docker-image.sh build docker.io/triphoop/rv-control-web:latest-amd64
```

Run only the command appropriate to the host. All builds, image tags, and
pushes must use `deploy/docker-image.sh`. A normal build uses Docker's
native/default platform unless `RV_WEB_PLATFORM` overrides it.

If the image must be transferred through Docker Hub, authenticate
interactively, then push the matching tag:

```sh
docker login --username triphoop
bash deploy/docker-image.sh push docker.io/triphoop/rv-control-web:latest-arm64
```

Use the AMD64 tag for an AMD64 image. Registry access must belong to the
logged-in account. The default build/push image is
`docker.io/triphoop/rv-control-web:latest`, but pushing both architectures to
that same tag overwrites it; it does not create a multi-architecture manifest.
Use versioned architecture-specific tags for reproducible releases and rollback.

## 2. Prepare external configuration

The image contains no runtime configuration or credentials. Use a host
directory outside the repository:

```sh
mkdir -p "$HOME/rv-control-web-config/assets"
```

For a **new production setup**, copy:

```sh
cp deploy/config.docker.yaml "$HOME/rv-control-web-config/config.yaml"
cp dashboard.example.yaml "$HOME/rv-control-web-config/dashboard.yaml"
```

Do not blindly repeat these copies over edited files. The required layout is:

```text
~/rv-control-web-config/
├── config.yaml
├── dashboard.yaml
├── auth-users.yaml
└── assets/
```

- `config.yaml`: broker, stream, dashboard path, asset path, and authentication.
- `dashboard.yaml`: installation-specific topics, payload paths, and widgets.
  The shipped example has Power and Shore Power tabs.
- `auth-users.yaml`: one to three accounts with password hashes.
- `assets/`: widget images; it may be empty for the shipped example.

Adapt topic bindings to captured device payloads; example topics are not
automatically discovered. Use the [testing guide](dashboard-testing.md) for
binding checks, derived readings, and sparkline configuration.

### Create accounts from the image

Run this on the deployment host using the selected image tag:

```sh
docker run --rm -it --network none \
  --user "$(id -u):$(id -g)" \
  --mount type=bind,source="$HOME/rv-control-web-config",target=/config \
  docker.io/triphoop/rv-control-web:latest-arm64 \
  python -m backend.app.setup_accounts --output /config/auth-users.yaml
```

Use the AMD64 tag on an AMD64 host. The helper asks for usernames and hidden,
confirmed passwords; press Enter at the next username prompt to finish.
It creates an owner-only `0600` credential file and refuses to overwrite an
existing one. It does not enable authentication or modify `config.yaml`.
Do not replace an existing credential file just to complete setup.

The writable mount is only for this one-off setup container. Compose mounts
the same directory read-only for the application. See
[authentication.md](authentication.md) for account changes and recovery.

### Configure production HTTPS and broker access

Edit the external `config.yaml`:

```yaml
mqtt:
  host: host.docker.internal
  port: 1883
  client_id: mqtt-dashboard
stream:
  tick_hz: 12
  stale_after_ms: 10000
dashboard_file: ./dashboard.yaml
assets_dir: ./assets
auth:
  credentials_file: ./auth-users.yaml
  origins:
    - https://rv.your-domain.example
  secure_cookie: true
```

Replace the browser domain; the origin must match exactly, without a path or
trailing slash. Do not retain localhost HTTP origins or
`secure_cookie: false` when moving a local setup into production.

`host.docker.internal` is mapped to the host gateway by Compose. A broker
listening only on host `127.0.0.1` is not reachable through that mapping.
Configure the broker to listen on an address reachable from the container,
with appropriate broker authentication and firewall restrictions, or set
`mqtt.host` to another reachable broker address. Do not expose MQTT publicly
just to solve container access.

Real MQTT credentials belong only in the external config. Password hashes,
Cloudflare tokens, and private installation payloads must never be committed
or added to the image.

## 3. Configure Compose and certificates

Create the untracked environment file, if it does not already exist:

```sh
cp deploy/.env.example deploy/.env
chmod 600 deploy/.env
```

Edit it with the actual values:

```dotenv
RV_WEB_IMAGE=docker.io/triphoop/rv-control-web:latest-arm64
RV_WEB_PLATFORM=linux/arm64
RV_WEB_DOMAIN=rv.your-domain.example
RV_WEB_CONFIG_DIR=/home/your-user/rv-control-web-config
CF_DNS_API_TOKEN=replace-with-your-private-token
```

For AMD64, change both image and platform to AMD64. Set
`RV_WEB_CONFIG_DIR` to the full absolute path; do not use a literal `~`.
`RV_WEB_DOMAIN` must match the HTTPS origin in `config.yaml`.
Compose defaults to ARM64 if no platform is provided, unlike the build script's
native default. The build script does not automatically read `deploy/.env`.

Set the ACME contact email in `deploy/traefik/traefik.yml`. Use a Cloudflare
DNS API token scoped to the required zone and permissions. DNS-01 certificate
validation does not require inbound port 80, but users still need network
access to HTTPS port 443. DNS must resolve the domain to the intended host;
firewall/router access must match how viewers will connect.

Prepare certificate storage **without truncating an existing certificate file**:

```sh
mkdir -p deploy/acme
touch deploy/acme/acme.json
chmod 600 deploy/acme/acme.json
```

For initial certificate testing, temporarily set the ACME `caServer` to
`https://acme-staging-v02.api.letsencrypt.org/directory` and use separate staging
storage. Staging certificates are not browser-trusted. Switch back to the
production CA and production storage before normal use.

Traefik publishes ports 80 and 443 and redirects HTTP to HTTPS. The backend
port is not published directly by the production Compose file. Traefik has
read-only access to the Docker socket for service discovery; treat that access
and DNS credentials as privileged deployment resources.

## 4. Start production

If using a registry image, pull it first. Skip `pull` for a freshly built local
image if you do not want the registry copy to replace it:

```sh
docker compose --env-file deploy/.env -f deploy/docker-compose.yml pull
docker compose --env-file deploy/.env -f deploy/docker-compose.yml up -d
```

Open `https://` followed by your `RV_WEB_DOMAIN`. Log in with an account created
by the setup helper.

Check services and logs:

```sh
docker compose --env-file deploy/.env -f deploy/docker-compose.yml ps
docker compose --env-file deploy/.env -f deploy/docker-compose.yml logs --tail=100 backend traefik
```

The backend must load credentials and connect to MQTT; Traefik must obtain a
certificate. `/healthz` requires an authenticated session, so an anonymous 401
is expected and is not evidence that the application is down. With a session,
inspect its JSON broker status; degraded broker health still returns HTTP 200.

Missing/invalid authentication settings abort startup instead of silently
opening the application. No account defaults or registration endpoint exist.

## 5. Updates, configuration changes, and rollback

After publishing a new image under the selected registry tag:

```sh
docker compose --env-file deploy/.env -f deploy/docker-compose.yml pull backend
docker compose --env-file deploy/.env -f deploy/docker-compose.yml up -d backend
```

For a freshly rebuilt **local** image, recreate the backend without pulling:

```sh
docker compose --env-file deploy/.env -f deploy/docker-compose.yml up -d --force-recreate backend
```

After external dashboard, broker, or credential changes:

```sh
docker compose --env-file deploy/.env -f deploy/docker-compose.yml restart backend
```

Restarting drops in-memory sessions and logs all viewers out. Refresh the
browser after dashboard layout changes. Run one backend process/worker:
sessions are not shared between instances.

After changing Compose environment values, run `up -d` to recreate affected
services; `restart` alone does not apply new container environment settings.
For Traefik static configuration changes, restart Traefik.

To roll back, set `RV_WEB_IMAGE` to a previous compatible, architecture-specific
version and run `up -d backend`. Preserve external configs, credentials, and
certificate storage. Back them up privately before major updates.

To stop the stack:

```sh
docker compose --env-file deploy/.env -f deploy/docker-compose.yml down
```

This does not delete the host configuration directory or certificate files.
The production stack never starts the fake MQTT publisher or test broker.

## Local UI-only Compose

For localhost access without Traefik, create a **new** external directory as
above, but copy `deploy/config.ui.yaml` as `config.yaml`. The existing local
directory prepared during development follows this layout already: its
credentials should be preserved, not copied over.

The UI config uses:

```yaml
auth:
  credentials_file: ./auth-users.yaml
  origins:
    - http://127.0.0.1:8000
  secure_cookie: false
```

Supply Compose values directly or use an untracked environment file:

```sh
RV_WEB_IMAGE=docker.io/triphoop/rv-control-web:latest \
RV_WEB_PLATFORM=linux/amd64 \
RV_WEB_CONFIG_DIR="$HOME/rv-control-web-config" \
docker compose -f deploy/docker-compose.ui.yml up -d
```

This command is for the AMD64 localhost setup with its native `latest` image.
Use the matching platform/tag on the Pi. Open <http://127.0.0.1:8000>. Port 8000
must be free: stop a previous local Uvicorn process or standalone
`rv-control-web` container before starting Compose. If you used the earlier
standalone container, stop it with `docker stop rv-control-web`; do not delete
unrelated containers.

The UI-only stack defaults to a localhost host-port bind. It has authentication
but no TLS proxy. Do not expose this HTTP setup to a LAN or the Internet.
For production use the Traefik stack and HTTPS settings above.

## Troubleshooting

| Symptom | Likely check |
| --- | --- |
| `exec format error` during build | Build natively on the matching host, or use a configured cross-architecture builder |
| Registry push denied | Use the Docker Hub namespace you can write to; image operations go through `docker-image.sh` |
| Container architecture mismatch | Match `RV_WEB_PLATFORM` and image tag to host |
| Backend repeatedly restarts | Credential file exists, config paths resolve, hashes/origins are valid; inspect backend logs |
| Login/logout 403 | `auth.origins` matches the browser's HTTPS origin exactly |
| Login cookie does not persist | Correct HTTPS/Secure-cookie settings; use the configured domain |
| No MQTT data | Broker reachable from container and topic paths correct; inspect broker/backend logs |
| Certificate failure | Domain/token permissions, ACME email, DNS access, certificate storage permissions |
| UI-only port conflict | Stop the previous backend/container explicitly or choose a different port and update allowed origin |
| Old config after an update | Restart backend for file changes; recreate containers for environment/image changes |
