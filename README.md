# RV Control Web

Read-only live MQTT dashboard with a Python/FastAPI backend and Svelte frontend.
Configure the broker in `config.yaml` and widget bindings in `dashboard.yaml`.
The example topics must be adapted to the payloads your devices publish.

## Local development

Requires Python 3.12+, Node.js 20+, and an MQTT broker on localhost:1883.

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

## Docker deployment

The default target is 64-bit Raspberry Pi OS (`linux/arm64`). Set
`RV_WEB_PLATFORM=linux/amd64` for an Intel/AMD host. Building for a different
architecture than the build machine requires emulation or a remote builder.
All image operations use the same script for people and CI:

```sh
bash deploy/docker-image.sh build rv-control-web:local
bash deploy/docker-image.sh tag rv-control-web:local docker.io/triphoop/rv-control-web:1
bash deploy/docker-image.sh push docker.io/triphoop/rv-control-web:1
```

For an AMD64 image, set the platform when building and use a distinct tag:

```sh
RV_WEB_PLATFORM=linux/amd64 bash deploy/docker-image.sh build docker.io/triphoop/rv-control-web:1-amd64
```

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

Keep real MQTT passwords and DNS credentials only in this external directory
and the untracked `deploy/.env`, never in the example files or image.

For the UI-only deployment, copy `deploy/config.ui.yaml` instead of
`deploy/config.docker.yaml`. Edit those copies for your MQTT broker and devices.
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
in `deploy/.env` to access it from a trusted LAN; it has no authentication or
TLS on its own. `deploy/config.ui.yaml` uses `host.docker.internal:1883` for a
broker running on the Docker host. That broker must listen on an address
reachable from the container, not only on `127.0.0.1`; otherwise set `mqtt.host`
to a reachable broker address in the external `config.yaml`.

Mosquitto in the Compose stack accepts local anonymous publishers; secure or
replace it before exposing the broker on an untrusted network.

The application and its configuration are independent of RV-Control except
for the MQTT topic and JSON payload contract. See `docs/architecture.md`.
