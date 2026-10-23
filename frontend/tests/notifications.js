import { createClassComponent } from 'svelte/legacy';
import { tick } from 'svelte';
import { get } from 'svelte/store';
import App from '../src/App.svelte';
import Notifications from '../src/Notifications.svelte';
import {
  notifications, notify, dismissNotification, clearNotifications, NOTIFICATION_DURATION,
} from '../src/notifications.js';
import '../src/style.css';

const fixture = document.querySelector('#fixture');
const results = document.querySelector('#results');
const checks = [];
const originalFetch = window.fetch;
const originalWebSocket = window.WebSocket;
const originalSetTimeout = window.setTimeout;
const originalClearTimeout = window.clearTimeout;
const originalUrl = location.href;
let component;

function assert(condition, message) {
  if (!condition) throw new Error(message);
  checks.push(message);
}

async function settle() {
  await new Promise((resolve) => originalSetTimeout(resolve, 0));
  await tick();
}

function button(text) {
  return [...fixture.querySelectorAll('button')].find((item) => item.textContent === text);
}

const sent = [];
let socket;
class MockWebSocket {
  static OPEN = 1;
  readyState = 0;
  constructor() {
    socket = this;
    queueMicrotask(() => {
      this.readyState = 1;
      this.onopen?.();
      this.receive({ type: 'config', config });
    });
  }
  send(data) { sent.push(JSON.parse(data)); }
  receive(message) { this.onmessage?.({ data: JSON.stringify(message) }); }
  close() { this.readyState = 3; this.onclose?.(); }
}

const control = (id, action) => ({ id, action, label: id, target: id, confirm: false });
const config = {
  app: { title: 'Notification test' },
  command_controls_enabled: true,
  query_controls_enabled: true,
  tabs: [{
    id: 'coach', label: 'Coach',
    root: { type: 'column', children: [
      { type: 'light', label: 'Test light', payload_path: 'light', controls: [control('light', 'toggle')] },
      { type: 'fan', payload_path: 'fan', controls: [control('fan', 'on')] },
      { type: 'generator', payload_path: 'generator', controls: [control('generator', 'start')] },
      { type: 'thermostat', payload_path: 'thermostat', controls: [control('thermostat', 'cool')] },
      { type: 'numeric', payload_path: 'number', controls: [control('generic', 'on')] },
      { type: 'wled', label: 'Test strip', entity: 'strip', controls: [
        control('wled', 'toggle'), control('wled_on', 'on'), control('wled_off', 'off'),
        { ...control('wled_brightness', 'brightness'), label: 'Brightness',
          input: { type: 'slider', param: 'bri', value_field: 'bri', min: 0, max: 255, step: 1 } },
        ...Object.entries({
          color: ['segment', 'red', 'green', 'blue'], effect: ['segment', 'effect_id'],
          palette: ['segment', 'palette_id'], transition: ['duration'], preset: ['preset_id'],
        }).map(([action, params]) => ({
          ...control(`wled_${action}`, action), label: action,
          input: { type: 'form', fields: params.map((param) => ({
            param, label: param, min: param === 'preset_id' ? 1 : 0,
            max: param === 'duration' ? 65535 : param === 'preset_id' ? 250 : 255, step: 1,
          })) },
        })),
      ] },
    ].map((node) => ({ ...node, topic: 'test' })) },
  }],
};

function snapshot(wled = { on: true, bri: 128, seg: [] }, ts = Date.now() / 1000) {
  socket.receive({ type: 'snapshot', tab: 'coach', values: [{
    topic: 'test', ts, payload: {
      light: false, fan: false, generator: { status: 'stopped' },
      thermostat: { mode: 'off', ambient_c: 22 }, number: 1, ...wled,
    },
  }] });
}

try {
  let clock = 0;
  let timerId = -1;
  const timers = new Map();
  window.setTimeout = (callback, delay) => {
    if (delay !== NOTIFICATION_DURATION) return originalSetTimeout(callback, delay);
    timers.set(--timerId, { callback, due: clock + delay });
    return timerId;
  };
  window.clearTimeout = (id) => {
    if (!timers.delete(id)) originalClearTimeout(id);
  };
  function advance(ms) {
    clock += ms;
    for (const [id, timer] of [...timers]) {
      if (timer.due <= clock) {
        timers.delete(id);
        timer.callback();
      }
    }
  }
  component = createClassComponent({ component: Notifications, target: fixture });
  const first = notify('First result');
  await tick();
  assert(fixture.querySelector('[role="status"]').textContent.includes('First result'),
    'Status notifications are announced');
  advance(1000);
  notify('Second result', { kind: 'error' });
  await tick();
  assert(fixture.querySelector('[role="alert"]').textContent.includes('Second result'),
    'Errors use an alert region');
  advance(3999);
  assert(get(notifications).length === 2, 'Notifications remain before five seconds');
  advance(1);
  assert(!get(notifications).some((item) => item.id === first)
    && get(notifications).length === 1, 'Each notification expires at exactly five seconds independently');
  advance(1000);
  assert(get(notifications).length === 0 && NOTIFICATION_DURATION === 5000,
    'Later notifications receive their own full five seconds');
  notify('Dismiss me');
  await tick();
  fixture.querySelector('button').click();
  await tick();
  assert(get(notifications).length === 0 && timers.size === 0,
    'Dismiss button removes the notification and its timer');
  const old = notify('Old');
  dismissNotification(old);
  notify('New');
  advance(4999);
  assert(get(notifications).length === 1, 'Old dismissals do not affect new notifications');
  clearNotifications();
  assert(get(notifications).length === 0 && timers.size === 0, 'Clear cancels all notification timers');
  component.$destroy();
  window.setTimeout = originalSetTimeout;
  window.clearTimeout = originalClearTimeout;

  window.WebSocket = MockWebSocket;
  let loggedIn = true;
  let logoutFails = false;
  window.fetch = async (url) => {
    if (url === '/api/auth/session') return Response.json({
      enabled: true, authenticated: loggedIn, username: 'viewer',
    });
    if (url === '/api/config') return Response.json(config);
    if (url === '/api/auth/login') return Response.json({ detail: 'Invalid credentials' }, { status: 401 });
    if (url === '/api/auth/logout') {
      if (logoutFails) return new Response(null, { status: 503 });
      loggedIn = false;
      return Response.json({});
    }
    throw new Error(`Unexpected request: ${url}`);
  };
  component = createClassComponent({ component: App, target: fixture });
  for (let attempt = 0; attempt < 30 && !button('Refreshing...'); attempt += 1) await settle();
  assert(sent.some((item) => item.type === 'refresh_states') && button('Refreshing...')?.disabled,
    'Coach refresh preserves pending feedback and disabled controls');
  const entities = Array.from({ length: 25 }, (_, index) => ({ entity: `light_${index}`, status: 'observed' }));
  socket.receive({ type: 'refresh_result', status: 'completed',
    message: 'Monitoring operation finished', data: { entities } });
  snapshot();
  await tick();
  assert(!button('Refresh Coach status').disabled
    && !fixture.querySelector('main').textContent.includes('Monitoring operation finished'),
  'Refresh completes without adding dashboard clutter');
  const details = fixture.querySelector('.notification details');
  assert(details && !details.open && details.querySelectorAll('li').length === 25,
    'All refresh entity details are preserved and collapsed');
  details.querySelector('summary').click();
  assert(details.open, 'Refresh details can be expanded');
  for (const [id, selector] of [
    ['light', '.light-status'], ['fan', '.fan-action'], ['generator', '.generator-action'],
    ['thermostat', '.thermostat-control-group button'], ['generic', '.control-actions button'],
    ['wled', 'button.wled-status'], ['wled_on', '.wled-actions button:first-child'],
    ['wled_off', '.wled-actions button:last-child'],
  ]) {
    fixture.querySelector(selector).click();
    await tick();
    assert(sent.at(-1).action_id === id && button('Refresh Coach status').disabled,
      `${id} action preserves dispatch and busy gating`);
    socket.receive({ type: 'command_result', action_id: id, status: 'completed',
      message: 'Configured action dispatched; physical state is not confirmed' });
    await tick();
    assert(!button('Refresh Coach status').disabled
      && !fixture.querySelector('main').textContent.includes('Configured action dispatched'),
    `${id} result uses notifications, not inline content`);
  }
  const slider = fixture.querySelector('.wled-slider input');
  for (const [action, params] of Object.entries({
    color: { segment: 2, red: 255, green: 80, blue: 20 },
    effect: { segment: 2, effect_id: 12 }, palette: { segment: 2, palette_id: 5 },
    transition: { duration: 10 }, preset: { preset_id: 250 },
  })) {
    const form = fixture.querySelector(`form[aria-label="Test strip ${action}"]`);
    const before = sent.length;
    for (const [param, value] of Object.entries(params)) {
      const input = form.querySelector(`[name="${param}"]`);
      input.value = String(value);
      input.dispatchEvent(new Event('input', { bubbles: true }));
    }
    await tick();
    assert(sent.length === before, `Editing WLED ${action} parameters does not dispatch`);
    form.querySelector('button').click();
    await tick();
    assert(sent.length === before + 1 && sent.at(-1).action_id === `wled_${action}`
      && JSON.stringify(sent.at(-1).value) === JSON.stringify(params)
      && form.querySelector('fieldset').disabled,
    `WLED ${action} submits all typed parameters once and respects busy gating`);
    socket.receive({ type: 'command_result', action_id: `wled_${action}`,
      status: 'completed', message: `${action} dispatched` });
    await tick();
    assert(!form.querySelector('fieldset').disabled
      && get(notifications).some((item) => item.message === `${action} dispatched`),
    `WLED ${action} results use shared notifications`);
  }
  const presetForm = fixture.querySelector('form[aria-label="Test strip preset"]');
  const presetInput = presetForm.querySelector('input');
  for (const value of ['0', '251', '1.5', '']) {
    presetInput.value = value;
    presetInput.dispatchEvent(new Event('input', { bubbles: true }));
    await tick();
    const before = sent.length;
    presetForm.querySelector('button').click();
    assert(sent.length === before && !presetForm.checkValidity(),
      `Invalid WLED preset input "${value}" is blocked by form validation`);
  }
  assert(slider.value === '128' && slider.max === '255' && slider.step === '1',
    'WLED brightness uses native telemetry and an integer 0–255 range');
  const beforeSlider = sent.length;
  slider.value = '200';
  slider.dispatchEvent(new Event('input', { bubbles: true }));
  await tick();
  assert(sent.length === beforeSlider, 'Dragging WLED brightness does not send commands');
  slider.dispatchEvent(new Event('change', { bubbles: true }));
  await tick();
  assert(sent.length === beforeSlider + 1 && sent.at(-1).action_id === 'wled_brightness'
    && sent.at(-1).value === 200 && slider.disabled,
  'Releasing WLED brightness sends exactly one action and gates controls while busy');
  assert(fixture.querySelector('.wled-brightness-label strong').textContent === '50%',
    'WLED command dispatch does not optimistically change reported brightness');
  clearNotifications();
  socket.receive({ type: 'command_result', action_id: 'wled_brightness', status: 'failed',
    message: 'WLED rejected' });
  await tick();
  assert(!slider.disabled && slider.value === '128'
    && get(notifications).some((item) => item.message === 'WLED rejected'),
  'Failed WLED commands restore telemetry-driven input and use shared notifications');
  snapshot({ on: false, bri: 64, seg: [] });
  await tick();
  assert(slider.value === '64' && fixture.querySelector('button.wled-status').textContent === 'Off',
    'WLED controls follow subsequent power and brightness telemetry');
  for (const [name, payload, ts] of [
    ['stale', { on: true, bri: 128 }, Date.now() / 1000 - 60],
    ['invalid', { on: 'bad', bri: 128 }, Date.now() / 1000],
    ['missing', {}, Date.now() / 1000],
  ]) {
    if (name === 'missing') socket.receive({ type: 'snapshot', tab: 'coach', values: [] });
    else snapshot(payload, ts);
    await tick();
    assert([...fixture.querySelectorAll('.wled button, .wled input')].every((item) => item.matches(':disabled')),
      `WLED controls are disabled with ${name} telemetry`);
  }
  snapshot();
  socket.receive({ type: 'config', config: { ...config, command_controls_enabled: false } });
  await tick();
  assert([...fixture.querySelectorAll('.wled button, .wled input')].every((item) => item.matches(':disabled')),
    'WLED controls respect the server write gate');
  socket.receive({ type: 'config', config });
  snapshot();
  await tick();
  socket.receive({ type: 'command_result', action_id: 'light', status: 'failed', message: 'Command rejected' });
  socket.receive({ type: 'refresh_result', status: 'failed', message: 'Refresh timed out' });
  socket.receive({ type: 'error', message: '<script>Untrusted error</script>' });
  await tick();
  assert(fixture.querySelector('[role="alert"]').textContent.includes('Command rejected')
    && fixture.querySelector('[role="alert"]').textContent.includes('Refresh timed out'),
  'Failed commands and refreshes use error notifications');
  assert(fixture.querySelector('[role="alert"]').textContent.includes('<script>Untrusted error</script>')
    && !fixture.querySelector('.notifications script'), 'Server errors render as text, not HTML');
  clearNotifications();
  fixture.querySelector('.light-status').click();
  socket.close();
  await tick();
  assert([...fixture.querySelectorAll('.wled button, .wled input')].every((item) => item.matches(':disabled')),
    'WLED controls are disabled after disconnect');
  assert(get(notifications).some((item) => item.message.includes('outcome is unknown')),
    'Disconnect during an action notifies the user of its unknown outcome');
  for (let attempt = 0; attempt < 30 && !button('Refreshing...'); attempt += 1) {
    await new Promise((resolve) => originalSetTimeout(resolve, 100));
    await tick();
  }
  assert(button('Refreshing...')?.disabled, 'Reconnect starts a new Coach refresh before disconnect testing');
  socket.close();
  await tick();
  assert(get(notifications).some((item) => item.message.includes('refresh finished')),
    'Disconnect during refresh also produces a notification');
  logoutFails = true;
  button('Logout').click();
  await settle();
  assert(get(notifications).some((item) => item.message === 'Logout failed (503)'),
    'Logout failures use the shared notification framework');
  logoutFails = false;
  button('Logout').click();
  await settle();
  assert(get(notifications).length === 0 && fixture.querySelector('#username'),
    'Logout clears old notifications and returns to login');
  fixture.querySelector('#username').value = 'viewer';
  fixture.querySelector('#username').dispatchEvent(new Event('input', { bubbles: true }));
  fixture.querySelector('#password').value = 'incorrect';
  fixture.querySelector('#password').dispatchEvent(new Event('input', { bubbles: true }));
  fixture.querySelector('form').dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }));
  await settle();
  assert(get(notifications).some((item) => item.message === 'Invalid credentials')
    && !fixture.querySelector('form [role="alert"]'), 'Login failures use notifications outside the form');
  component.$destroy();
  assert(get(notifications).length === 0, 'Application teardown clears notifications');
  component = null;
  results.textContent = `PASS (${checks.length} checks)\n${checks.join('\n')}`;
} catch (error) {
  results.textContent = `FAIL: ${error.stack}\nPassed checks:\n${checks.join('\n')}`;
  throw error;
} finally {
  component?.$destroy();
  clearNotifications();
  window.fetch = originalFetch;
  window.WebSocket = originalWebSocket;
  window.setTimeout = originalSetTimeout;
  window.clearTimeout = originalClearTimeout;
  history.replaceState(null, '', originalUrl);
}
