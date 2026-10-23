# RV Control Web

Live MQTT dashboard with a Python/FastAPI backend and Svelte frontend. Coach
entity commands are configurable and disabled by default.
Configure the broker in `config.yaml` and widget bindings in `dashboard.yaml`.
The example topics must be adapted to the payloads your devices publish.

## Documentation

- [Changelog](CHANGELOG.md)
- [Architecture and integration boundaries](docs/architecture.md)
- [Production Docker Compose runbook](docs/deployment.md): external config
  directory, image-based account setup, HTTPS, updates, and localhost Compose
- [Viewer authentication setup](docs/authentication.md): accounts, password
  hashes, allowed origins, HTTPS cookies, and session behavior
  (includes an interactive credential-file creator runnable from the image)
- [Dashboard features and local MQTT testing](docs/dashboard-testing.md):
  complete startup/restart workflow, fake telemetry configuration, sample
  validation, sparklines, derived readings, notifications, and troubleshooting
- [Shared UI notification pattern](docs/architecture.md#131-shared-notifications-and-feedback):
  reusable API, lifecycle, accessibility, and guidance for future UI feedback
- [WLED controls](docs/dashboard-testing.md#wled-controls): Coach entity binding,
  power, brightness, RGB color, effects, palettes, transitions, and saved presets

## UI feedback

Coach refresh and configured action results appear as rounded notifications
at the bottom-right, not inside widgets. Notifications disappear after five
seconds or can be dismissed manually; refresh entity details can be expanded.
Application errors use the same system. Live telemetry remains the source of
physical-state confirmation.

New frontend feedback should reuse the
[shared notification API](docs/architecture.md#131-shared-notifications-and-feedback).
See [notification regression checks](docs/dashboard-testing.md#notifications)
for the browser-only test workflow.

## Local development

Requires Python 3.12+, Node.js 20+, and an MQTT broker on localhost:1883.
Normal configurations require authentication. Before starting the backend,
create external credentials and configure allowed browser origins using the
[authentication guide](docs/authentication.md). The fake-data test setup below
explicitly disables authentication for local testing only.

```sh
python -m venv backend/.venv
backend/.venv/bin/pip install -r backend/requirements.txt
backend/.venv/bin/uvicorn backend.app.main:app --reload
```

In another terminal:

```sh
cd frontend
npm install
npm run dev
```

Open http://127.0.0.1:5173. When no broker is available, the UI still loads
with no-data readings and `/healthz` reports a degraded connection. Run
`npm run build` to let the backend serve the built UI on port 8000.

### Local fake MQTT data

See the [complete testing guide](docs/dashboard-testing.md) for configuration
reference, restart instructions, and validation limits.

To try the dashboard without RV-Control or a real broker, start the test-only
Mosquitto broker (bound to localhost only):

```sh
docker compose -f deploy/docker-compose.test.yml up -d
```

In separate terminals, start the dashboard with its test configuration and the
fake telemetry publisher:

```sh
RV_WEB_CONFIG=config.test.yaml backend/.venv/bin/uvicorn backend.app.main:app --reload
backend/.venv/bin/python -m backend.app.fake_mqtt
```

The publisher reads `fake-mqtt.example.yaml` and publishes **only the topics
referenced by the dashboard** selected in `config.test.yaml`. The shipped
scenario includes `rv/renogy`, `rv/hughes`, and `rv/wled/patio`, matching the
current dashboard's devices. The test dashboard example has Power and Shore
Power tabs using `rv/renogy` and `rv/hughes`.
Open http://127.0.0.1:8000
or use the frontend dev server at http://127.0.0.1:5173. Stop the publisher
with Ctrl+C and remove the broker with
`docker compose -f deploy/docker-compose.test.yml down`.
The broker permits anonymous connections for local testing only and must not
be exposed to a network.

#### Configuring fake telemetry

Copy `fake-mqtt.example.yaml` to a local scenario file and edit its topics and
payload fields. For a different dashboard, pass its runtime configuration:

```sh
backend/.venv/bin/python -m backend.app.fake_mqtt \
  --scenario /path/to/my-scenario.yaml --dashboard-config config.yaml
```

`--dashboard-config` selects dashboard bindings only: the publisher still
connects to the local test broker, not the broker in that file. Use `--host`
and `--port` explicitly to change the publisher's broker. Do not point it at
a production broker.

Each topic has a `payload` template and optional `interval_s`, `qos`, and
`retain`. Defaults are the scenario's `interval_s` (1 second when omitted),
QoS 0, and retained messages. Topics absent from the selected dashboard are
ignored; missing dashboard topics or bindings abort startup with an error.
Nested objects and arrays are supported.

Plain payload values stay constant. A value can instead use a generator:

```yaml
interval_s: 1
topics:
  rv/renogy:
    interval_s: 2
    retain: true
    payload:
      battery_percentage:
        generator: sine
        min: 20
        max: 95
        period_s: 120
        decimals: 1
      charging_status:
        generator: sequence
        values: [charging, idle]
        hold_s: 30
```

This snippet illustrates the format; include every field referenced by your
selected dashboard in the full scenario.

- `sine`: smoothly oscillates between `min` and `max` over `period_s`, starting
  at the midpoint and rising.
- `ramp`: rises from `min` toward `max`, then resets every `period_s`.
- `sequence`: cycles through scalar `values`, holding each for `hold_s`.
  Use `[true, false]` for a toggling boolean.
- Numeric generators accept `decimals` from 0 to 6 (default 1); 0 emits integers.

Changes follow elapsed seconds, independent of how often a topic publishes.
Restart the publisher after changing configuration. Values are independent
test signals, not a physical simulation of related voltage/current/power.
Validate without starting a publisher, or save its initial payloads for the
dashboard checker:

```sh
backend/.venv/bin/python -m backend.app.fake_mqtt --check
```

## Docker deployment

**Production uses Docker Compose with Traefik.** Follow the
[deployment runbook](docs/deployment.md) for the complete sequence, including
external configuration, account creation, HTTPS origins, and certificate setup.
The UI-only Compose file is for localhost testing or a separately secured
proxy, not a replacement for the production HTTPS stack.

Builds use Docker's native/default platform unless `RV_WEB_PLATFORM` is set.
On an AMD64 host, a normal build produces an AMD64 image. Building for a
different architecture requires emulation or a remote builder.
All image operations use the same script for people and CI:

```sh
bash deploy/docker-image.sh build
bash deploy/docker-image.sh push
```

`build` and `push` default to `docker.io/triphoop/rv-control-web:latest` when `IMAGE:TAG` is
omitted. Pass an explicit image to override it. `tag` still requires both
source and destination. The default image includes the Docker Hub namespace,
so no extra tagging step is needed between build and push.

For architecture-specific images, use distinct tags:

```sh
RV_WEB_PLATFORM=linux/amd64 bash deploy/docker-image.sh build docker.io/triphoop/rv-control-web:1-amd64
RV_WEB_PLATFORM=linux/arm64 bash deploy/docker-image.sh build docker.io/triphoop/rv-control-web:1-arm64
```

The ARM64 command on an AMD64 host still requires an ARM64-capable builder;
the script does not install emulation.

To control a local UI container without Docker Compose, build the image with
`deploy/docker-image.sh`, then point `RV_WEB_CONFIG_DIR` at a directory containing
`config.yaml`, `dashboard.yaml`, `auth-users.yaml`, and `assets/`:

```sh
bash deploy/docker-image.sh build
RV_WEB_CONFIG_DIR="$HOME/rv-control-web-config" bash deploy/docker-ui.sh start
bash deploy/docker-ui.sh status
bash deploy/docker-ui.sh stop
```

The control script binds to `127.0.0.1:8000` by default. Set `RV_WEB_BIND` or
`RV_WEB_PORT` to change the host binding. The config directory is mounted
read-only. Dashboard image sources remain relative to `assets/` and are served
under the protected `/assets/` route; `/ui-assets/` serves the compiled frontend.
Configure accounts and matching browser origins using the
[authentication guide](docs/authentication.md). Changing `RV_WEB_PORT` also
requires changing the allowed origin. The helper starts an existing container
with its original settings; changed image, bind, or mount settings require
deliberate container recreation. Production uses
[Docker Compose with HTTPS](docs/deployment.md), not this local helper.

Set `RV_WEB_PLATFORM=linux/amd64` and
`RV_WEB_IMAGE=docker.io/triphoop/rv-control-web:1-amd64` in `deploy/.env` when
deploying that image. Both Compose files use `RV_WEB_PLATFORM` (defaulting to
`linux/arm64`); the build script reads it from the environment, not from
`deploy/.env` automatically.

Authenticate with `docker login --username triphoop` before pushing; enter
credentials interactively and never store them in tracked files.

The image contains no runtime configuration. On the Pi, put the configuration
and any widget images in a host directory outside the repository:

```sh
mkdir -p "$HOME/rv-control-web-config/assets"
cp deploy/config.docker.yaml "$HOME/rv-control-web-config/config.yaml"
cp dashboard.example.yaml "$HOME/rv-control-web-config/dashboard.yaml"
```

Keep viewer password hashes, real MQTT passwords, and DNS credentials only in this external directory
and the untracked `deploy/.env`, never in the example files or image.

The full stack keeps Traefik but does not run an MQTT broker. It uses
`deploy/config.docker.yaml`, which connects to a broker on the Docker host.
For the UI-only deployment, copy `deploy/config.ui.yaml` instead. Edit the
selected config for your MQTT broker and devices.
Set `RV_WEB_CONFIG_DIR` to the absolute path of that directory in an untracked
`deploy/.env`, alongside `RV_WEB_IMAGE`. The full stack also requires
`RV_WEB_DOMAIN` and `CF_DNS_API_TOKEN`; use `deploy/.env.example` as a template.
Both Compose files mount the directory read-only
at `/config`, and the backend loads `/config/config.yaml`. Image paths in the
dashboard are relative to `/config/assets`. Set the ACME contact email in
`deploy/traefik/traefik.yml`, then create `deploy/acme/acme.json` with mode 600
before starting the full stack:

```sh
docker compose --env-file deploy/.env -f deploy/docker-compose.yml up -d
```

To run only the UI application (Python API plus Svelte frontend), with no
Traefik or Mosquitto container:

```sh
docker compose --env-file deploy/.env -f deploy/docker-compose.ui.yml up -d
```

The UI-only stack binds `127.0.0.1:8000` by default. Set `RV_WEB_BIND=0.0.0.0`
in `deploy/.env` only behind an HTTPS proxy with the corresponding
authentication origins and Secure cookies configured; it has no TLS on its
own. See the [authentication guide](docs/authentication.md).
`deploy/config.ui.yaml` uses `host.docker.internal:1883` for a
broker running on the Docker host. That broker must listen on an address
reachable from the container, not only on `127.0.0.1`; otherwise set `mqtt.host`
to a reachable broker address in the external `config.yaml`.

The application and its configuration are independent of RV-Control except
for the MQTT topic and JSON payload contract. See `docs/architecture.md`.
