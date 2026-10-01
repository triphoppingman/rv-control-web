# RV Control Web: Architecture and Design Specification

## Table of Contents

1. [Overview](#1-overview)
2. [Integration Boundary](#2-integration-boundary)
3. [Goals and Non-Goals](#3-goals-and-non-goals)
4. [Assumptions and Locked Decisions](#4-assumptions-and-locked-decisions)
5. [Requirements](#5-requirements)
6. [High-Level Architecture](#6-high-level-architecture)
7. [Technology Stack](#7-technology-stack)
8. [Component Architecture](#8-component-architecture)
9. [Configuration](#9-configuration)
10. [Data Binding and Payload Extraction](#10-data-binding-and-payload-extraction)
11. [WebSocket Protocol](#11-websocket-protocol)
12. [Backend Design Detail](#12-backend-design-detail)
13. [Frontend Design Detail](#13-frontend-design-detail)
14. [Widget Catalog](#14-widget-catalog)
15. [Responsive and Layout Model](#15-responsive-and-layout-model)
16. [Deployment and Operations](#16-deployment-and-operations)
17. [Security Considerations](#17-security-considerations)
18. [Performance and Scalability](#18-performance-and-scalability)
19. [Future Extensions](#19-future-extensions)
20. [Repository Structure](#20-repository-structure)
21. [Build Plan and Milestones](#21-build-plan-and-milestones)
22. [Acceptance Criteria](#22-acceptance-criteria)
23. [Copilot Implementation Guidance](#23-copilot-implementation-guidance)
24. [Appendix A: Backend Model Sketches](#appendix-a-backend-model-sketches)
25. [Appendix B: Frontend Type Sketches](#appendix-b-frontend-type-sketches)

## 1. Overview

The RV Control Web is a web application that renders live telemetry
published to an MQTT broker. A Python backend owns one set of MQTT
subscriptions, caches the latest value for every topic, and streams updates to
browsers over WebSocket. A Svelte frontend renders a configurable, responsive
display composed of nested containers and widgets, driven by a YAML file
authored at deployment time.

The display is organized into tabs. Only the widgets on the currently displayed
tab receive live updates. Widgets may be data-bound (gauges, dials, numeric
readouts, and boolean indicators) or static (text, images, dividers, and
spacers). The layout is a tree of containers for flexible composition across
phones, tablets, and large monitors.

The first release is read-only. A future release may add a write path that
publishes to MQTT from the UI; this design reserves the protocol and security
boundaries for that feature without implementing it now.

## 2. Integration Boundary

The dashboard integrates with RV-Control exclusively through the MQTT broker.
RV-Control is an external MQTT publisher from the dashboard's perspective.
The dashboard must not import RV-Control modules, read its INI configuration,
call its HTTP or command-line interfaces, inspect its files, or depend on its
process lifecycle.

The only shared contract is the broker connection and the published MQTT
messages:

- RV-Control publishes JSON telemetry to its configured MQTT topics.
- The dashboard subscribes to the topics named by bound widgets in
  `dashboard.yaml`.
- The dashboard treats topic names and JSON payload shapes as configuration;
  they are not resolved through RV-Control code or configuration files.
- Both applications may run on the same host and connect to the same broker,
  but they remain independently deployable and restartable.

For a default RV-Control setup, a dashboard topic may look like
`rv/rvc/<dgn-name>` or `rv/<source-topic>`, depending on the source and its
configured topic. The dashboard should document the exact topics and payload
paths used by a particular installation in its own dashboard configuration.

### 2.1 MQTT payload contract

RV-Control publishes each telemetry object by calling `publish(topic, payload)`.
The publisher prepends the configured `base_topic` (default `rv`) and encodes
the object with JSON. Therefore, the dashboard must subscribe to the complete
topic, including the base prefix, and bind to fields in the object itself. It
must not expect an additional envelope such as `{ "data": ... }`.

The payload shapes at the MQTT boundary are:

- **RV-C:** topic `rv/rvc/<name>`; payload contains `dgn`, `name`, `source`,
  `data`, and the decoded named fields from the RV-C specification. For
  example, a decoded temperature field may be addressed as `temperature` or
  `temperature_c`, depending on the specification name.
- **Renogy:** topic `rv/<configured-topic>` (normally `rv/renogy`); payload is
  the merged reading object from the selected Renogy client and includes
  `__device` and `__client`. Rover controller readings may include
  `battery_percentage`, `battery_voltage`, `battery_current`, `pv_power`, and
  `charging_status`; the available fields depend on the device type.
- **Hughes:** topic `rv/<configured-topic>` (normally `rv/hughes`); a single-leg
  payload contains `line`, `voltage`, `current`, `power`, `energy`, and
  `error_code`. A 50 A combined payload uses fields such as
  `voltage_line_1`, `voltage_line_2`, `power_line_1`, and `power_line_2`.
- **WLED:** topic `rv/<configured-topic>` (for example `rv/wled/patio`);
  payload is the WLED `/json/state` object, with fields such as `on`, `bri`,
  `seg`, and `transition` supplied by the WLED device.

The dashboard configuration is installation-specific: only bind to fields that
the selected device actually publishes. When a source or device type changes,
update the dashboard bindings from a captured MQTT payload rather than
assuming that similarly named sources have identical schemas.

## 3. Goals and Non-Goals

### Goals

- Render live MQTT telemetry with sub-second visual updates.
- Configure widgets, containers, and tabs through a deployment-time YAML file.
- Reflow cleanly across phones, tablets, and desktop monitors.
- Support data-bound and static widgets in a flexible, nestable layout.
- Support approximately 200 devices on one host, with only the active tab
  streamed to each client.
- Preserve a clean extension path to future write and control capabilities.

### Non-Goals (v1)

- No historical storage or time-series querying. The system is instantaneous.
- No in-app layout editor. Configuration is authored in YAML at deployment.
- No publishing to MQTT from the UI.
- No multi-broker federation.
- No user-specific dashboards. All viewers see the same dashboard.

## 4. Assumptions and Locked Decisions

| ID | Decision | Consequence |
| --- | --- | --- |
| D1 | The dashboard is purely instantaneous. | Use an in-memory last-value cache; do not add a time-series store. |
| D2 | The first release is read-only. | Use WebSocket so a future write path can be added without changing transports. |
| D3 | Display and layout are configured by YAML at deployment time. | Validate configuration at startup; reloading requires a restart. |
| D4 | Payloads are JSON. | Parse each message once; widgets bind to fields through `payload_path`. |
| D5 | The system supports approximately 200 devices across multiple tabs. | Use one backend process and no external fan-out bus. |
| D6 | Only the displayed tab is active. | Stream only the active tab while caching current values in memory. |
| D7 | The display is a recursive tree of containers and widgets. | `topic` and `payload_path` are required only for bound widgets. |
| D8 | The MQTT broker runs on the web server host. | The backend connects to the broker through `localhost`. |
| D9 | TLS is terminated by Traefik using Let's Encrypt DNS-01. | No inbound port 80 or 443 is required for certificate validation. |
| D10 | RV-Control integration is MQTT-only. | No shared Python package, configuration file, API, filesystem path, or process dependency is required. |
| D11 | No payload versioning is used in the first release. | The subscriber consumes the documented JSON fields directly; schema version negotiation is deferred. |
| D12 | The backend is Python and the frontend is Svelte. | Implement server-side logic in Python and the browser UI in Svelte. |

## 5. Requirements

### 5.1 Functional Requirements

- **FR-1:** Load and validate runtime configuration and dashboard YAML at
  startup; invalid configuration aborts startup with a clear error.
- **FR-2:** Derive the distinct MQTT topics used by bound widgets and subscribe
  to them.
- **FR-3:** Cache the latest parsed payload, raw string, and receive timestamp
  for each subscribed topic.
- **FR-4:** Accept live MQTT messages and populate the in-memory cache after connection.
- **FR-5:** Allow a browser client to request updates for exactly one active tab.
- **FR-6:** Send a snapshot of cached values when a client subscribes to a tab,
  then stream updates.
- **FR-7:** Coalesce pending updates per client and flush one batch at a
  configurable tick rate, sending only the latest value per topic per tick.
- **FR-8:** Fetch dashboard configuration and render the tab bar and active tree.
- **FR-9:** Mount only the active tab and replace its subscription on tab switch.
- **FR-10:** Extract bound values from topic payloads through `payload_path`.
- **FR-11:** Render static widgets from configuration without topic subscriptions.
- **FR-12:** Reconnect automatically after WebSocket loss and resubscribe.
- **FR-13:** Show stale and no-data states for bound widgets.
- **FR-14:** Support nested grid, row, column, stack, and card containers.

### 5.2 Non-Functional Requirements

- **NFR-1, latency:** Broker-to-browser visual latency is under approximately
  150 ms on localhost, excluding tick quantization. The default tick is 80 ms.
- **NFR-2, responsiveness:** Layout works from approximately 320 px to large
  desktop monitors using container-relative breakpoints.
- **NFR-3, scale:** Approximately 200 devices and their widgets run in one process.
- **NFR-4, resource safety:** A slow client cannot create unbounded pending data;
  per-client buffers conflate values.
- **NFR-5, robustness:** Malformed payloads are logged and skipped without
  crashing the stream; the last good value remains cached.
- **NFR-6, portability:** The backend runs on Python 3.12 and the frontend
  builds to static assets.
- **NFR-7, maintainability:** Configuration, MQTT, cache, and fan-out logic are
  independent of the web transport layer and unit-testable.

## 6. High-Level Architecture

The Python backend is a gateway. It owns MQTT subscriptions, normalizes and
caches messages, and fans out updates to browsers over WebSocket. The browser
does not connect directly to the broker.

Per-client data path:

1. The client loads the SPA and fetches `/api/config`.
2. The client opens `/ws` and sends `subscribe` with a tab ID.
3. The server sends a `snapshot` for cached topics in that tab.
4. The server sends coalesced `update` frames at the configured tick rate.
5. On tab switch, the client subscribes to the new tab and receives a snapshot.

## 7. Technology Stack

| Layer | Choice | Rationale |
| --- | --- | --- |
| Broker | Mosquitto | Existing MQTT broker for live telemetry delivery. |
| Backend runtime | Python 3.12 | Target runtime. |
| Web framework | FastAPI and Uvicorn | Async HTTP and WebSocket support. |
| MQTT client | `aiomqtt` | Async MQTT integration with the event loop. |
| Configuration | PyYAML and Pydantic v2 | YAML input and discriminated-union validation. |
| Frontend | Svelte, using SvelteKit static output or Vite | Small compiled client and straightforward reactivity. |
| Charts and gauges | ECharts; uPlot optional for sparklines | Canvas-based gauges and efficient charts. |
| Edge and TLS | Traefik v3 | Single-origin routing and Let's Encrypt DNS-01. |
| Packaging | Docker Compose or systemd | Suitable for a single-host deployment. |

## 8. Component Architecture

### 8.1 Backend modules

```text
backend/
  app/
    main.py             # ASGI app, HTTP routes, WebSocket, static files
    settings.py         # Runtime configuration and validation
    dashboard.py        # Dashboard YAML, models, and topic derivation
    mqtt_gateway.py     # One MQTT client, subscriptions, and message loop
    cache.py             # LastValueCache: topic -> payload, raw, timestamp
    hub.py               # Client registry, buffers, and fan-out ticker
    protocol.py          # WebSocket message models
    logging_conf.py      # Logging setup
  tests/
    test_dashboard.py
    test_cache.py
    test_hub.py
    test_protocol.py
```

`cache.py`, `hub.py`, `mqtt_gateway.py`, and `dashboard.py` do not import the
web framework. `main.py` is the only module that knows about FastAPI and
WebSocket objects.

### 8.2 Frontend structure

```text
frontend/
  src/
    lib/
      config.js          # Dashboard configuration loading
      socket.js          # WebSocket connection and reconnect logic
      store.js           # Topic state and snapshot/update appliers
      path.js            # Dotted paths and array-index extraction
      value.js           # Formatting, thresholds, and staleness
    components/
      Node.svelte        # Recursive container/widget renderer
      TabBar.svelte
      containers/
        Grid.svelte
        Row.svelte
        Column.svelte
        Stack.svelte
        Card.svelte
      widgets/
        Gauge.svelte
        Dial.svelte
        Numeric.svelte
        Boolean.svelte
        Sparkline.svelte
        Text.svelte
        Image.svelte
        Icon.svelte
        Divider.svelte
        Spacer.svelte
    App.svelte
    main.js
  static/
```

### 8.3 Broker and edge router

Mosquitto runs on `localhost:1883`. The dashboard does not depend on retained
messages. After a subscriber or backend restart, values become available as
soon as RV-Control publishes new telemetry.

Traefik is the single public entry point. It terminates TLS, serves or routes
the frontend, and proxies `/api/*` and `/ws`. WebSocket upgrades are automatic.
The backend binds to `127.0.0.1:8000` and is not exposed directly.

## 9. Configuration

There are two configuration files with different lifecycles:

- `config.yaml` contains operational settings and is owned by operations.
- `dashboard.yaml` contains the display tree and controls what is shown.

### 9.1 Runtime configuration

```yaml
server:
  host: 127.0.0.1
  port: 8000

mqtt:
  host: 127.0.0.1
  port: 1883
  username: null
  password: null
  client_id: mqtt-dashboard
  qos: 0
  keepalive: 60

stream:
  tick_hz: 12
  stale_after_ms: 10000

dashboard_file: ./dashboard.yaml
assets_dir: ./assets
log_level: INFO
```

### 9.2 Dashboard configuration

```yaml
app:
  title: "RV Control - Live"

tabs:
  - id: power
    label: "RV Battery"
    root:
      type: grid
      cols: 12
      gap: 16
      children:
        - type: card
          title: "Battery overview"
          subtitle: "Renogy controller telemetry"
          span: 3
          children:
            - type: gauge
              id: battery_charge
              topic: rv/renogy
              payload_path: battery_percentage
              label: Battery charge
              unit: "%"
              min: 0
              max: 100
              decimals: 0
              thresholds:
                - { at: 20, color: red }
                - { at: 50, color: amber }
                - { at: 80, color: green }
            - type: divider
              orientation: horizontal
            - type: numeric
              topic: rv/renogy
              payload_path: battery_voltage
              label: Battery voltage
              unit: "V"
              decimals: 1

        - type: card
          title: "Solar input"
          span: 5
          children:
            - type: row
              gap: 12
              wrap: true
              children:
                - type: numeric
                  topic: rv/renogy
                  payload_path: pv_voltage
                  label: PV voltage
                  unit: "V"
                  decimals: 1
                  min_width: "150px"
                - type: numeric
                  topic: rv/renogy
                  payload_path: pv_current
                  label: PV current
                  unit: "A"
                  decimals: 2
                  min_width: "150px"
                - type: gauge
                  topic: rv/renogy
                  payload_path: pv_power
                  label: PV power
                  unit: "W"
                  min: 0
                  max: 1000
                  decimals: 0
                  min_width: "220px"

        - type: card
          title: "Controller status"
          span: 4
          children:
            - type: text
              variant: caption
              content: "Live values from rv/renogy"
            - type: numeric
              topic: rv/renogy
              payload_path: controller_temperature
              label: Controller temperature
              unit: "F"
              decimals: 1
            - type: numeric
              topic: rv/renogy
              payload_path: load_power
              label: Load power
              unit: "W"
              decimals: 0
            - type: spacer
              size: "8px"

        - type: card
          title: "Notes"
          span: 8
          children:
            - type: text
              variant: body
              content: "Telemetry is read directly from the MQTT broker."
            - type: image
              src: rv-overview.png
              alt: "RV system overview"
              fit: contain
              height: "180px"

        - type: card
          title: "WLED patio"
          span: 4
          children:
            - type: boolean
              topic: rv/wled/patio
              payload_path: on
              label: Light power
              true_label: "On"
              false_label: "Off"
              true_color: green
              false_color: gray
            - type: numeric
              topic: rv/wled/patio
              payload_path: bri
              label: Brightness
              decimals: 0

  - id: shore-power
    label: "Shore Power"
    root:
      type: column
      gap: 16
      children:
        - type: text
          variant: heading
          content: "Hughes Power Watchdog"
        - type: row
          gap: 12
          wrap: true
          children:
            - type: numeric
              topic: rv/hughes
              payload_path: voltage
              label: Voltage
              unit: "V"
              decimals: 1
              min_width: "180px"
            - type: numeric
              topic: rv/hughes
              payload_path: current
              label: Current
              unit: "A"
              decimals: 2
              min_width: "180px"
            - type: gauge
              topic: rv/hughes
              payload_path: power
              label: Power
              unit: "W"
              min: 0
              max: 5000
              decimals: 0
              min_width: "240px"
        - type: card
          title: "Protection status"
          children:
            - type: numeric
              topic: rv/hughes
              payload_path: error_code
              label: Error code
              decimals: 0
```

This example matches the Rover controller payload emitted by the default
`renogy_controller` configuration. It is valid only when that device type is
publishing `battery_percentage`; other Renogy clients require different field
bindings.

A node is a discriminated union on `type` with three families:

- Containers have `children`.
- Bound widgets require `topic` and `payload_path`.
- Static widgets have no topic and render from configuration only.

Common fields are `type`, optional `id`, `span`, `min_width`, `visible`, and
`class`. Container types are `grid`, `row`, `column`, `stack`, and `card`.
Bound widget types are `gauge`, `dial`, `numeric`, `boolean`, and `sparkline`.
Static types are `text`, `image`, `icon`, `divider`, and `spacer`.

Validation rules:

- `type` must be known.
- Bound widgets require a non-empty `topic` and `payload_path`.
- Static widgets must not contain `topic` or `payload_path`.
- Gauges, dials, and sparklines require `min < max`.
- Image sources must resolve below `assets_dir`; absolute and external URLs are
  rejected.
- Tab IDs must be unique. Node IDs should be unique within the dashboard.
- Errors identify the tab and node path that failed validation.

## 10. Data Binding and Payload Extraction

`payload_path` addresses a field inside a topic's JSON payload. It uses a dotted
path with optional `$` prefix and array indices, for example `temp_c`,
`$.temp_c`, `sensors.inlet.temp`, or `readings[0].value`.

Missing segments resolve to `undefined`, and the widget shows no-data. Multiple
widgets may bind to different paths on the same topic; the backend subscribes
once and deduplicates topics.

Thresholds are sorted by `at`. The active color is the highest threshold whose
`at` is less than or equal to the value. Color tokens such as `red`, `amber`,
`green`, `blue`, and `gray` map to theme colors; CSS colors are also allowed.

For boolean widgets, an omitted `on_when` uses truthiness. A scalar `on_when`
requires strict equality, such as `on_when: RUNNING`.

- **No-data:** no cached topic value exists or the path is undefined.
- **Stale:** the last value exists, but `now - ts` exceeds `stale_after_ms`.

## 11. WebSocket Protocol

Endpoint: `GET /ws`, upgraded to WebSocket. Text frames contain JSON. Every
message has a `type` discriminator. Message type names are lowercase.

### 10.1 Client to server

```json
{ "type": "subscribe", "tab": "line1" }
```

```json
{ "type": "unsubscribe", "tab": "line1" }
```

### 10.2 Server to client

```json
{
  "type": "snapshot",
  "tab": "line1",
  "values": [
    {
      "topic": "rv/renogy",
      "payload": {
        "battery_percentage": 87,
        "battery_voltage": 13.4,
        "battery_current": 4.2,
        "pv_power": 185,
        "charging_status": "charging",
        "__device": "RV Controller",
        "__client": "RoverClient"
      },
      "ts": 1757800000.12
    }
  ]
}
```

```json
{
  "type": "update",
  "values": [
    {
      "topic": "rv/renogy",
      "payload": {
        "battery_percentage": 88,
        "battery_voltage": 13.5,
        "battery_current": 4.0,
        "pv_power": 190,
        "charging_status": "charging",
        "__device": "RV Controller",
        "__client": "RoverClient"
      },
      "ts": 1757800000.30
    }
  ]
}
```

```json
{ "type": "error", "code": "unknown_tab", "message": "No tab with id 'linex'." }
```

The server sends nothing until subscription. On close or error, the client
reconnects with exponential backoff, capped at approximately 10 seconds, then
resubscribes. Non-object JSON payloads are wrapped as `{ "value": <payload> }`.

REST endpoints:

- `GET /api/config` returns the dashboard tree and client settings.
- `GET /healthz` returns status, MQTT connectivity, cached topic count, and
  connected-client count.

## 12. Backend Design Detail

### 11.1 Startup sequence

1. Load and validate `config.yaml`.
2. Load and validate `dashboard.yaml`.
3. Walk every tab and derive `all_topics` and `tab_topics`.
4. Start the MQTT gateway and subscribe to `all_topics`.
5. Start the global fan-out ticker.
6. Start the ASGI server.

### 11.2 MQTT gateway and cache

There is one MQTT client. For each message it decodes UTF-8, parses JSON, logs
and skips malformed payloads, wraps non-object JSON, updates the cache, and
notifies the hub. Broker disconnects use bounded backoff; the cache is rebuilt
from messages received after reconnection.

The cache maps topics to records containing `payload`, `raw`, and `ts`. Its size
is bounded by the number of subscribed topics. Single-event-loop access makes
the cache async-safe without locks.

### 11.3 Client hub and fan-out

Each client has an active tab, a topic set, and a pending map of topic to latest
value. Subscribing sets the active tab, sends a snapshot for cached topics, and
clears pending values. Topic updates replace pending values for interested
clients. A single global ticker sends one update frame per client and clears its
pending map. Disconnect removes the client and its buffers.

Unknown tabs return `unknown_tab` without changing the active tab. Send
failures disconnect and clean up the client. MQTT disconnects are retried and
reported by `/healthz`.

## 13. Frontend Design Detail

1. Fetch `/api/config` and store tabs and settings.
2. Select the first tab, or the tab named by an optional `tab` query parameter.
3. Open WebSocket and subscribe to the active tab.
4. Apply snapshots by replacing relevant topic state and updates by merging it.
5. On tab switch, clear the old tab's state and subscribe to the new tab.

`Node.svelte` recursively renders containers and maps widget types to components.
Only bound widgets read the topic store. Static widgets render only from config.
Only the active tab root is mounted, so hidden tabs incur no rendering cost.

Gauges and dials use ECharts and resize through `ResizeObserver`. Numeric and
boolean widgets apply formatting, thresholds, and stale/no-data styles. An
optional sparkline keeps a client-side rolling buffer that resets on tab switch
or reconnect. Static content must never be rendered as raw HTML.

## 14. Widget Catalog

- **Containers:** `grid`, `row`, `column`, `stack`, `card`
- **Bound widgets:** `gauge`, `dial`, `numeric`, `boolean`, `sparkline`
- **Static widgets:** `text`, `image`, `icon`, `divider`, `spacer`

## 15. Responsive and Layout Model

Use CSS grid and flexbox rather than absolute positioning. A grid maps to
`display: grid` with `repeat(cols, minmax(0, 1fr))`; a child's `span` sets its
grid-column span. Rows and columns map to flexbox, and `min_width` allows
children to wrap.

Container queries drive breakpoints so nested layouts respond to their own
width. Below a threshold, a 12-column grid can collapse to fewer columns and
row children can stack. Gauges and dials resize with their container. Verify
layouts at approximately 320, 768, 1280, and 1920 or more pixels.

## 16. Deployment and Operations

- Mosquitto runs at `localhost:1883` and is not exposed through Traefik.
- Uvicorn serves FastAPI at `127.0.0.1:8000`, including static assets, `/api`,
  and `/ws`.
- Traefik is the only process bound to public ports 80 and 443.
- Widget images live below `assets_dir` and are served under `/assets`.

Recommended Docker Compose services are `traefik`, `backend`, and Mosquitto.
Mount configuration, dashboard YAML, assets, Traefik configuration, and
persistent `acme.json`. Inject DNS-provider credentials through an untracked
environment file or secret; never commit them.

Provide one Bash script, `deploy/docker-image.sh`, as the sole entry point for
Docker image build, tag, and push operations. It must support both interactive
user use and non-interactive machine use through explicit arguments; do not
duplicate these commands in separate deployment scripts or CI steps.

Deploying a new `dashboard.yaml` requires restarting the backend so topic
subscriptions are re-derived. Commit `config.example.yaml` and
`dashboard.example.yaml`, but never environment-specific secrets.

DNS-01 proves domain control by creating an `_acme-challenge` TXT record through
the DNS provider API. It supports wildcard certificates and does not require
inbound port 80 or 443 during issuance or renewal.

Example Traefik configuration:

```yaml
entryPoints:
  web:
    address: ":80"
    http:
      redirections:
        entryPoint:
          to: websecure
          scheme: https
  websecure:
    address: ":443"

certificatesResolvers:
  le:
    acme:
      email: ops@example.com
      storage: /letsencrypt/acme.json
      dnsChallenge:
        provider: cloudflare
        resolvers: ["1.1.1.1:53", "8.8.8.8:53"]

providers:
  docker:
    exposedByDefault: false
```

Create `acme.json` with mode 600 before first use. Test against the Let's
Encrypt staging CA before switching to production. WebSocket upgrades need no
special Traefik configuration.

## 17. Security Considerations

- Authentication is intentionally out of scope for the initial implementation.
  The UI, `/api`, and `/ws` are unauthenticated and should remain on a trusted
  network until a future authentication design is implemented.
- Use HTTPS and WSS in the browser; Traefik redirects HTTP to HTTPS.
- Keep DNS credentials out of source control and protect `acme.json`.
- Treat MQTT payloads as untrusted. Parse safely, validate numeric values, and
  never render payloads through Svelte `{@html}`.
- Restrict image sources to `assets_dir` and reject absolute or external URLs.
- A future write path requires authorization, a server-side topic allow-list,
  QoS 1, and an audit log.

## 18. Performance and Scalability

Coalescing at 12 Hz bounds the per-client send rate even when publishers run at
high frequency. Tab scoping limits each client to its active tab. The expected
ceiling is client-side rendering, so keep widget counts reasonable and avoid
layout work on every frame.

One process is sufficient for approximately 200 devices. If multiple backend
instances become necessary, add a shared pub/sub system for cross-instance
fan-out. That is outside the scope of v1.

## 19. Future Extensions

- Write and control widgets with command/ack messages, authorization, allow-lists,
  QoS 1 publishing, and auditing.
- Authentication and per-user dashboards.
- Short-term server-side history or a time-series store.
- In-app layout editing with editable configuration.
- Derived widgets computed from multiple topics.
- SIGHUP-based dashboard hot reload.

## 20. Repository Structure

```text
mqtt-live-dashboard/
  backend/
  frontend/
  deploy/
    docker-compose.yml
    docker-image.sh       # Build, tag, and push entry point for users and CI
    traefik/traefik.yml
    acme/acme.json       # Gitignored; mode 600
    .env.example         # DNS provider variables only
    systemd/             # Optional systemd units
  config.example.yaml
  dashboard.example.yaml
  assets/
  README.md
```

## 21. Build Plan and Milestones

- **M1, backend core:** Settings, dashboard validation, topic derivation, MQTT
  gateway, cache, `/api/config`, `/healthz`, and one-tab WebSocket flow.
- **M2, tab-scoped fan-out:** Client hub, conflation, ticker, and multi-tab flow.
- **M3, frontend skeleton:** Config fetch, reconnecting WebSocket client, store,
  tab bar, recursive node renderer, numeric widget, and text widget.
- **M4, widget catalog:** Gauges, dials, booleans, images, icons, dividers,
  spacers, containers, formatting, thresholds, and state styles.
- **M5, responsive resilience:** Container queries, chart resizing, status
  indicator, reconnect polish, and viewport verification.
- **M6, deployment:** Compose, Traefik, DNS-01 certificates, static and asset
  serving, example configuration, and operational documentation.
- **M7, future:** Write path and authentication.

## 22. Acceptance Criteria

- **AC-1:** Valid dashboard configuration boots, `/api/config` returns the tree,
  and the backend subscribes to exactly the distinct bound-widget topics.
- **AC-2:** Publishing to a subscribed topic updates active-tab widgets within
  approximately one tick on desktop and mobile viewports.
- **AC-3:** Switching tabs immediately renders current cached values and stops
  updates for the previous tab.
- **AC-4:** Missing data displays no-data; an inactive topic becomes stale after
  `stale_after_ms`.
- **AC-5:** Static widgets render correctly and never create subscriptions.
- **AC-6:** Malformed JSON is logged without breaking other topics or the stream.
- **AC-7:** A slow client does not cause unbounded backend memory growth.
- **AC-8:** Nested layouts reflow across phone and monitor widths.
- **AC-9:** Invalid dashboard configuration aborts startup with a located error.
- **AC-10:** After a backend restart, new live MQTT publications repopulate the
  cache and update the dashboard without requiring retained messages.
- **AC-11:** Traefik obtains a DNS-01 certificate, redirects HTTP to HTTPS, and
  successfully proxies WebSocket connections.

## 23. Copilot Implementation Guidance

- Stay pragmatic: make the smallest justified change and avoid speculative
  edge cases, repeated analysis, or unnecessary process.
- Conserve tokens: read only relevant context and keep updates and explanations
  concise.
- Validate proportionately: run focused checks for changed behavior, but do
  not repeat tests or run unrelated suites without a concrete reason.
- Leave Git operations, including staging, commits, branches, Git tags, and
  pushes, to the user. Do not perform them on the user's behalf.
- Route Docker image builds, tags, and pushes through `deploy/docker-image.sh`
  for both people and automation; never invoke those operations independently.

## Appendix A: Backend Model Sketches

Illustrative Pydantic v2 models; these are not final application code.

```python
from typing import Annotated, Literal, Optional, Union

from pydantic import BaseModel, Field


class NodeBase(BaseModel):
    id: Optional[str] = None
    span: Optional[int] = None
    min_width: Optional[str] = None
    visible: bool = True
    css_class: Optional[str] = Field(default=None, alias="class")


class Threshold(BaseModel):
    at: float
    color: str


class BoundBase(NodeBase):
    topic: str
    payload_path: str
    label: Optional[str] = None
    stale_after_ms: Optional[int] = None


class Gauge(BoundBase):
    type: Literal["gauge", "dial"]
    unit: Optional[str] = None
    min: float
    max: float
    decimals: int = 1
    thresholds: list[Threshold] = []


class Numeric(BoundBase):
    type: Literal["numeric"]
    unit: Optional[str] = None
    decimals: int = 1
    thresholds: list[Threshold] = []


class Boolean(BoundBase):
    type: Literal["boolean"]
    true_label: str = "true"
    false_label: str = "false"
    true_color: str = "green"
    false_color: str = "gray"
    on_when: Optional[object] = None


class Text(NodeBase):
    type: Literal["text"]
    content: str
    variant: Literal["heading", "subheading", "body", "caption"] = "body"
    align: Optional[str] = None


class Image(NodeBase):
    type: Literal["image"]
    src: str
    alt: Optional[str] = None
    fit: Literal["contain", "cover", "fill"] = "contain"


class Container(NodeBase):
    type: Literal["grid", "row", "column", "stack", "card"]
    cols: int = 12
    gap: int = 12
    title: Optional[str] = None
    subtitle: Optional[str] = None
    wrap: bool = False
    align: Optional[str] = None
    justify: Optional[str] = None
    children: list["Node"] = []


Node = Annotated[
    Union[Container, Gauge, Numeric, Boolean, Text, Image],
    Field(discriminator="type"),
]


class Tab(BaseModel):
    id: str
    label: str
    icon: Optional[str] = None
    root: Node


class Dashboard(BaseModel):
    app: dict
    tabs: list[Tab]
```

Topic derivation walks the tree and collects each bound widget's topic:

```python
def collect_topics(node: Node) -> set[str]:
    topics: set[str] = set()
    topic = getattr(node, "topic", None)
    if topic:
        topics.add(topic)
    for child in getattr(node, "children", []) or []:
        topics |= collect_topics(child)
    return topics
```

## Appendix B: Frontend Type Sketches

```ts
type ClientMsg =
  | { type: "subscribe"; tab: string }
  | { type: "unsubscribe"; tab: string };

type TopicValue = {
  topic: string;
  payload: Record<string, unknown>;
  ts: number;
};

type ServerMsg =
  | { type: "snapshot"; tab: string; values: TopicValue[] }
  | { type: "update"; values: TopicValue[] }
  | { type: "error"; code: string; message: string };

type TopicStore = Map<
  string,
  { payload: Record<string, unknown>; ts: number }
>;
```