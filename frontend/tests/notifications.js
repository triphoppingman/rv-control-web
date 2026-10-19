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
    ].map((node) => ({ ...node, topic: 'test' })) },
  }],
};

function snapshot() {
  socket.receive({ type: 'snapshot', tab: 'coach', values: [{
    topic: 'test', ts: Date.now() / 1000, payload: {
      light: false, fan: false, generator: { status: 'stopped' },
      thermostat: { mode: 'off', ambient_c: 22 }, number: 1,
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
  assert(get(notifications).some((item) => item.message.includes('outcome is unknown')),
    'Disconnect during an action notifies the user of its unknown outcome');
  await new Promise((resolve) => originalSetTimeout(resolve, 550));
  await tick();
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
