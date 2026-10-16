# Dashboard features and local MQTT testing

This guide covers sample-payload validation, browser-only trends, derived
readings, and the configurable fake MQTT setup. For deployment instructions,
see the [README](../README.md); for the application design, see
[architecture.md](architecture.md).

## Boundaries

- The application remains read-only. Neither the browser nor the application
  backend publishes MQTT commands.
- The fake publisher is a separate development tool. Mosquitto supplies the
  actual MQTT broker; the publisher supplies synthetic telemetry.
- No RV-Control code, configuration, or process dependency is used.
- Viewer login is implemented; this local test setup explicitly disables it.
  See [authentication.md](authentication.md) to test login or configure a
  deployment. Role-based authorization remains deferred.
- No database, server-side history, layout editor, or physical device simulator
  is introduced by these features.

## Configuration files

| File | Purpose |
| --- | --- |
| [config.test.yaml](../config.test.yaml) | Test backend settings; localhost broker on port 1883, example dashboard, 12 Hz streaming, 10-second default staleness |
| [dashboard.example.yaml](../dashboard.example.yaml) | Shipped Power, Shore Power, and OBD2 tabs |
| [fake-mqtt.example.yaml](../fake-mqtt.example.yaml) | Synthetic payload templates and change patterns |
| [docker-compose.test.yml](../deploy/docker-compose.test.yml) | Test-only Mosquitto service in Compose project `rv-web-test` |
| [mosquitto.test.conf](../deploy/mosquitto.test.conf) | Anonymous test broker with persistence disabled |

The local installation can also have `config.yaml` and `dashboard.yaml`.
Those files are gitignored and may differ from the examples. Do not assume
their contents match another installation.

Hughes bindings depend on the device's published payload. The example uses
single-leg fields (`voltage`, `current`, `power`, `energy`, `error_code`).
A combined two-leg payload instead uses those names with `_line_1` and
`_line_2` suffixes, including `error_code_line_1` and `error_code_line_2`.
Configure separate widgets for each leg using the exact published field names.
A connected UI can show `No data` even while MQTT messages arrive when its
`payload_path` fields do not match the payload. After correcting the bindings,
save the dashboard; the backend reloads it and updates connected browsers.

The example dashboard has:

| Tab | Topic | Widgets |
| --- | --- | --- |
| Power | `rv/renogy` | State-of-charge gauge and trend, PV-to-battery voltage delta, PV power |
| Shore Power | `rv/hughes` | Line-voltage gauge, current, power trend, error code, energy |
| OBD2 | `rv/obd` | RPM, speed, engine load, coolant and transmission temperatures, intake and ambient air, fuel, barometric pressure, voltage, gear, raw torque converter clutch |

OBD bindings use the configured MQTT topic, not the source section name
(`obd_engine`). The example uses `rv/obd` and only active PID fields; disabled
exhaust-gas and boost PIDs have no widgets or fake readings. Verify topic names,
available fields, and temperature units against your publisher's MQTT payload
and PID definitions before using these bindings with a different installation.

The scenario also defines `rv/wled/patio` for dashboards with lighting widgets.
It is not published when the selected dashboard does not reference it.
It also defines `rv/tanks` with independent integer sequences for
`fresh_level`, `gray_level`, and `black_level`. Fresh cycles 3, 2, 1, 0 every
10 seconds per step; gray and black cycle 0, 1, 2, 3 with 15- and 20-second
steps respectively. The topic publishes every two seconds with retention.
These synthetic levels exercise empty, thirds, and full states, not physical
tank behavior. Tank telemetry is selected only when the chosen test dashboard
binds to `rv/tanks`; no tanks are added to the live dashboard.
The publisher selects topics across **all** dashboard tabs; the application
streams only the active tab's topics to each viewer.

## Starting the complete local test setup

Run all commands from the repository root. Prerequisites are Python 3.12+,
Node.js 20+, Docker with Compose, and the development dependencies installed
as described in the [README](../README.md#local-development).

### 1. Start the broker

```sh
docker compose -f deploy/docker-compose.test.yml up -d
```

The host port is bound to `127.0.0.1:1883`. No application Docker image needs
to be built for this workflow. If a broker already occupies that port, do not
stop it blindly: use a different test port as described below.

### 2. Start the backend

In a terminal:

```sh
RV_WEB_CONFIG=config.test.yaml backend/.venv/bin/uvicorn \
  backend.app.main:app --host 127.0.0.1 --port 8000
```

`RV_WEB_CONFIG` chooses the backend runtime configuration. Relative
`dashboard_file` and `assets_dir` paths are resolved from that file's directory.
Dashboard YAML is checked for changes every second. Valid edits automatically
update connected browsers, preserving the selected tab if it still exists
(otherwise selecting the first tab). Widgets remount, clearing browser-only
chart history. Topic changes reconnect MQTT with the updated subscriptions.
Invalid edits are logged and shown in connected browsers while the last valid
dashboard continues running; save a corrected file to recover automatically.
Runtime settings in `config.yaml` still require a backend restart.

### 3. Start fake telemetry

In another terminal:

```sh
backend/.venv/bin/python -m backend.app.fake_mqtt \
  --scenario fake-mqtt.example.yaml --dashboard-config config.test.yaml
```

The publisher logs its connection and selected topics. The shipped setup
publishes Renogy readings every second and Hughes readings every two seconds.
Both use retained messages.

### 4. Open the dashboard

For frontend development, in another terminal:

```sh
cd frontend
npm run dev
```

Open <http://127.0.0.1:5173/?tab=power> or
<http://127.0.0.1:5173/?tab=shore>. Vite proxies API and WebSocket traffic
to the backend on port 8000.

Alternatively, build once with `npm --prefix frontend run build`, then restart
the backend if it was started before the build. The backend serves the built
dashboard at <http://127.0.0.1:8000>. Rebuild after frontend changes when using
this option.

## Restarting and stopping

| Changed file or behavior | Required action |
| --- | --- |
| Dashboard YAML | Save; connected browsers update automatically within about a second |
| Backend runtime settings | Stop backend with Ctrl+C, restart it, then reload the browser |
| Scenario YAML | Stop publisher with Ctrl+C and restart it |
| Dashboard topic list | Restart both backend and publisher with matching dashboard selections |
| Test Mosquitto settings or Compose ports | Recreate the test broker with the Compose commands below |
| Frontend code | Vite updates the dev UI; built UI needs a new build |

Stop the publisher and backend with Ctrl+C in their own terminals. Stop Vite
similarly if it is running. Remove the isolated test broker with:

```sh
docker compose -f deploy/docker-compose.test.yml down
```

Then start it again with `up -d` when needed. No persistent broker volume is
used. Retained messages survive a publisher stop while the broker is running,
but are lost when the broker restarts. If you need a clean test after removing
topics, restart the test broker rather than relying on the publisher to remove
old retained messages.

## Fake telemetry CLI

| Option | Default | Meaning |
| --- | --- | --- |
| `--scenario` | `fake-mqtt.example.yaml` | YAML scenario, relative to the current working directory |
| `--dashboard-config` | `config.test.yaml` | Runtime config selecting the dashboard to inspect |
| `--host` | `127.0.0.1` | Publisher's MQTT broker |
| `--port` | `1883` | Publisher's MQTT port, 1-65535 |
| `--check` | Off | Validate and print initial payloads without connecting |

`--dashboard-config` does **not** select the publisher's broker. It uses only
the dashboard and asset paths. The publisher has no MQTT username/password
or TLS options and is intended for the anonymous local test broker. Never
point it at a production broker.

To select a different installation's dashboard:

```sh
backend/.venv/bin/python -m backend.app.fake_mqtt \
  --dashboard-config config.yaml --scenario /path/to/my-scenario.yaml
```

To avoid a port conflict, change the test Compose host mapping to
`127.0.0.1:1884:1883`, set `mqtt.port: 1884` in the backend's test config,
recreate the broker, and pass `--port 1884` to the publisher.

## Scenario reference

Copy the [shipped scenario](../fake-mqtt.example.yaml) and customize it.
Its top-level settings are `interval_s` and `topics`. Each `topics` key must
be a complete, concrete MQTT topic: wildcard topics are not publishable.

| Topic setting | Default | Validation |
| --- | --- | --- |
| `payload` | Required | JSON-compatible object, array, or scalar template |
| `interval_s` | Top-level `interval_s`, or 1 second | Positive finite number |
| `qos` | 0 | Integer 0, 1, or 2 |
| `retain` | `true` | Boolean `true` or `false` |

Unknown settings are rejected for selected topics. Topics not referenced by
the dashboard are ignored, including their templates. Missing dashboard topics
or payload paths fail before a connection is attempted.

Plain values remain constant. Nested objects and arrays preserve their shape.
A dictionary containing `generator` is reserved for a generator definition:

```yaml
interval_s: 1
topics:
  rv/hughes:
    interval_s: 2
    qos: 0
    retain: true
    payload:
      voltage: {generator: sine, min: 118, max: 122, period_s: 60, decimals: 1}
      current: {generator: sequence, values: [2, 4, 6], hold_s: 15}
      power: {generator: sine, min: 240, max: 720, period_s: 40, decimals: 1}
      error_code: 0
      energy: {generator: ramp, min: 0, max: 10, period_s: 3600, decimals: 3}
```

This is a complete Hughes template for the example Shore Power tab. A complete
scenario for the two-tab dashboard also needs the Renogy entry.

### Generators

| Generator | Required settings | Behavior |
| --- | --- | --- |
| `sine` | `min`, `max`, `period_s` | Smooth periodic oscillation; starts at midpoint and rises |
| `ramp` | `min`, `max`, `period_s` | Rises from minimum toward maximum, resets each period |
| `sequence` | Non-empty scalar `values`, `hold_s` | Repeats values in order, holding each for the configured time |

Numeric bounds and their difference must be finite, with `min < max`.
Periods and hold times must be positive and finite. Sine/ramp generators
accept `decimals` from 0 to 6, default 1; 0 emits integers.
Sequences support numbers, strings, booleans, and null as general template
values, but null is rejected when that sequence supplies a dashboard binding.
Numeric chart and derived bindings also reject non-numeric sequence values.

Generators use monotonic elapsed seconds rather than a tick counter. Topic
intervals therefore affect sampling, not waveform speed. Long publish intervals
can skip sequence states or parts of a waveform. The publisher retries broker
failures with backoff from 1 to 10 seconds; after reconnect it resumes using
elapsed time. Restarting the publisher restarts the generators.

Signals are independent. Synthetic power is not computed from synthetic
voltage/current, and ramped energy resets rather than modeling a real meter.
Use these signals to test display behavior, not physical correctness.

## Checking dashboard bindings

The [sample checker](../backend/app/check_dashboard.py) is offline: it does not
connect to MQTT. Supply a JSON object whose keys are complete MQTT topics and
whose values are representative payloads. Use exactly the selected dashboard's
topic set, including derived inputs.

Generate samples from the scenario and check them:

```sh
backend/.venv/bin/python -m backend.app.fake_mqtt \
  --dashboard-config config.test.yaml --check > /tmp/rv-web-samples.json
backend/.venv/bin/python -m backend.app.check_dashboard \
  --config config.test.yaml --samples /tmp/rv-web-samples.json
```

The checker reports node paths such as `tabs[0].root.children[0]`. A successful
check prints tab, binding, and topic counts and exits 0. Validation/file errors
go to stderr and exit 1; invalid CLI arguments exit 2. Its config defaults to
`RV_WEB_CONFIG` when set, otherwise `config.yaml`.

Paths support dotted fields, an optional `$` prefix, and array indices:
`battery_voltage`, `$.battery_voltage`, or `readings[0].value`. Non-object
MQTT payloads are wrapped by the backend as `{"value": ...}`, so bind those
widgets to `value` or an indexed path under it.

The checker rejects missing paths, non-finite numeric bindings, and non-finite
derived results such as division by zero. It checks representative values, not
every point of a generated waveform.

**Validation difference:** the current checker requires numbers for every
`numeric` widget, while the UI and fake publisher permit string-valued numeric
readouts such as charging status. Such a dashboard can run but fail this
strict offline check. The example test dashboard uses numeric readouts only.
The fake publisher checks derived inputs, but not every derived result; use
the sample checker and live testing for those results.

Keep captured installation payloads outside version control if they contain
private information. Generated sample files are disposable.

## Low-fuel and low-battery dial warnings

The fuel and house battery state-of-charge dials set `low_warning_below: 15`
with `min: 0` and `max: 100`.
This places the red arc at the start of the dial, from empty to 15%, and
leaves the remaining arc in its normal color, including at full charge.
The setting is dial-only and
must be a finite number strictly between `min` and `max`, in the dial's units.
Without this setting, dials retain their existing red zone over the top 20%
of the range. Other gauges and widget threshold colors are unchanged.

Set `show_warning: false` on a dial to remove the red warning arc and ticks.
The default is `true`, preserving existing dial warning zones. For a voltage
dial centered on 120 V at the top, use `min: 90` and `max: 150` (the midpoint
of the symmetric needle sweep is 120). This changes the displayed scale only,
not the telemetry value or protection settings.

## Segmented tank levels

Use `type: tank` for a vertical bar that fills from bottom to top:

```yaml
type: tank
label: Fresh water
topic: rv/tanks
payload_path: fresh_level
min: 0
max: 3
segments: 3
decimals: 0
```

This illustrative binding maps numeric values 0, 1, 2, 3 to empty, one-third,
two-thirds, and full. Replace the topic and field with your captured MQTT
payload; the widget consumes one numeric level, not separate sensor booleans.
For quarter increments, use `max: 4` and `segments: 4`. Percentage readings
can use `min: 0`, `max: 100`, and either segment count.

Every tank is a separate widget with its own `label`, topic, field, and range.
For example, place these widgets in an existing tab's layout to show three
tanks side by side (using illustrative fields):

```yaml
type: flow
children:
  - type: tank
    label: Fresh water
    topic: rv/tanks
    payload_path: fresh_level
    max: 3
    segments: 3
    min_width: 160px
  - type: tank
    label: Gray water
    topic: rv/tanks
    payload_path: gray_level
    max: 3
    segments: 3
    min_width: 160px
  - type: tank
    label: Black water
    topic: rv/tanks
    payload_path: black_level
    max: 3
    segments: 3
    min_width: 160px
```

The label appears above each bar and is also its screen-reader label.
Tanks can share a topic with separate payload fields or use different topics.
To test this layout, add it to a separate test dashboard, point a test runtime
config's `dashboard_file` at that file, and pass that config to the faker:

```sh
backend/.venv/bin/python -m backend.app.fake_mqtt \
  --scenario fake-mqtt.example.yaml --dashboard-config /path/to/test-config.yaml --check
```

Remove `--check` to publish to the local test broker. The faker still selects
only the dashboard topics and validates all generated tank sequence values as
numeric before connecting. The selected config does not change the faker's
broker; keep production dashboards and brokers out of this test workflow.

Defaults are `min: 0`, `max: 100`, and `segments: 3`. Bounds must be finite
numbers with `min < max`; segment count must be an integer from 1 to 20.
The normalized value is rounded to the nearest whole segment. Values outside
the scale clamp the bar to empty/full while preserving the actual numeric
reading below it. No-data and invalid readings leave the bar unfilled with
an explicit status, rather than claiming a valid empty tank.

Standard `unit`, `decimals`, `thresholds`, `stale_after_ms`, and layout settings
apply. Thresholds color the filled segments; no warning zones are assumed.
Empty segments and labels follow the selected theme. The bar uses CSS, not
an additional charting dependency.

The browser checks at `/tests/charts.html` also cover tank increments,
clamping, missing/invalid readings, themes, thresholds, and stale status.

## Browser-only trends

Chart rendering is split into `Dial.svelte` (needle instruments),
`Gauge.svelte` (arc gauges), and `Sparkline.svelte` (sampled line history).
They share `Chart.svelte` for ECharts initialization, resizing, and disposal.
`Node.svelte` still owns recursive containers, telemetry bindings, labels,
and stale/missing indicators; dashboard YAML types are unchanged.

To run the chart component regression checks, start the frontend with
`npm --prefix frontend run dev`, then open
<http://127.0.0.1:5173/tests/charts.html>. The page reports PASS or FAIL for
needle scales and warnings, arc gauges, live updates, themes, sparkline
sampling/history, resizing, and cleanup. These checks mount real components
with synthetic readings and also verify derived readings update when telemetry
arrives and become stale as time advances; no backend or MQTT broker is needed.
Keep the test tab visible to exercise container resizing; that check is
explicitly reported as skipped when the tab is hidden.

Add `type: sparkline` with ordinary `topic` and `payload_path` bindings:

```yaml
type: sparkline
label: Power trend
topic: rv/hughes
payload_path: power
unit: W
min: 0
max: 1000
history_points: 120
sample_interval_ms: 2000
```

| Setting | Default | Allowed range |
| --- | --- | --- |
| `history_points` | 60 | Integer 2-1000 |
| `sample_interval_ms` | 1000 | Integer 0-60000 |
| `min`, `max` | 0, 100 | Finite numbers with `min < max` |

The buffer accepts a reading when its backend receive timestamp is newer than
the previous accepted timestamp and the interval has elapsed. Zero interval
accepts each distinct timestamp delivered to the browser. This is sampling,
not aggregation: there is no averaging or min/max bucket calculation.
Backend update conflation can already discard intermediate MQTT readings.

With regular two-second readings, 120 points cover approximately four minutes.
This is a point-count limit, not a fixed-duration window. The horizontal axis
uses evenly spaced point indices, so irregular timing and outages are not
shown as proportional time gaps.

Only mounted widgets collect history. Switching tabs remounts the tree and
discards its history; page refresh also discards it. A WebSocket reconnect on
the same mounted tab does not explicitly clear the buffer. No server history
is fetched and no data is persisted.

## Derived numeric widgets

A `derived` widget declares input bindings instead of its own `topic` and
`payload_path`:

```yaml
type: derived
label: PV-to-battery voltage delta
operation: difference
unit: V
decimals: 2
inputs:
  - topic: rv/renogy
    payload_path: pv_voltage
  - topic: rv/renogy
    payload_path: battery_voltage
```

| Operation | Inputs | Calculation |
| --- | --- | --- |
| `sum` | At least 2 | Sum of inputs |
| `difference` | Exactly 2 | First minus second |
| `product` | At least 2 | Product of inputs |
| `ratio` | Exactly 2 | First divided by second |
| `average` | At least 2 | Sum divided by input count |

All distinct input topics participate in normal tab subscriptions. Calculations
use the latest cached value for each input, which may come from different
receive times. There is no synchronization, unit conversion, arbitrary code
execution, expression language, or derived-to-derived binding.

Readings use normal numeric formatting and thresholds. `unit` is display text;
choose compatible input units and sign conventions yourself.
`stale_after_ms` can override the global threshold for the widget's inputs.
Missing/null inputs produce `No data`; non-numeric inputs and non-finite
results produce `Invalid input`; otherwise any stale input marks the result
`Stale`. A valid stale calculation still displays its last computed value.
Division by zero is invalid rather than an estimate or zero-valued fallback.

## Health and troubleshooting

```sh
curl --fail http://127.0.0.1:8000/healthz
curl --fail http://127.0.0.1:8000/api/config
docker compose -f deploy/docker-compose.test.yml ps
docker compose -f deploy/docker-compose.test.yml logs mqtt
```

For the anonymous fake-data two-tab setup, expect `mqtt_connected: true` and two cached
topics after telemetry arrives. `/healthz` returns HTTP 200 even for degraded
broker state: inspect its JSON `status` and `mqtt_connected`, not just curl's
exit status. With authentication enabled, `/healthz` requires a session.
Browser `Live telemetry` indicates a WebSocket connection, not
independent confirmation of broker health.

| Symptom | Check |
| --- | --- |
| Only Power tab appears | Confirm the selected dashboard includes `shore`; valid dashboard edits reload automatically. Changing the runtime config selection requires a restart. `/api/config` should include `shore` |
| No data | Check publisher logs, scenario topic/path coverage, and backend broker settings |
| Stale readings | Check publish interval versus `stale_after_ms`; stop the publisher to exercise staleness |
| MQTT reconnect warnings | Check broker is running and ports agree; publishers and backend retry automatically |
| Address already in use | Identify the existing listener before restarting anything; use an alternate test broker port if needed |
| No change in a signal | Check it is a generator rather than a static value, its period, rounding, and sampling interval |
| Derived value is missing/invalid | Check all input paths, types, timestamps, and divisor; use the offline checker |
| Old values return on reconnect | Retained messages remain while broker runs; recreate the test broker for a clean cache |
| Sparkline resets on tab switch | Expected browser-only behavior |

The broker is anonymous and local-only, with no TLS or persistence. Its Compose
project is separate from production services. Do not change it to a public
bind address or treat it as an authentication solution.

## Verification coverage

Run the focused backend tests:

```sh
backend/.venv/bin/python -m unittest \
  backend.tests.test_fake_mqtt backend.tests.test_dashboard_features -v
```

They cover dashboard topic derivation, sample paths/types, derived arity,
generator output, invalid configuration, offline check mode, and per-topic
scheduling/QoS/retention. Tests do not need a real broker.

The implementation was also checked against a real local Mosquitto instance
for topic delivery, changing readings, and retained delivery. Power and Shore
Power navigation and Shore Power live readings were verified in the browser.
These checks do not establish full browser coverage for derived updates,
sparkline edge cases, outages, or all responsive sizes; keep those in manual
acceptance testing. No authentication/authorization review is implied.
