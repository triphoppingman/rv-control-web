import { writable } from 'svelte/store';

export const NOTIFICATION_DURATION = 5000;

const store = writable([]);
const timers = new Map();
let nextId = 0;

export const notifications = { subscribe: store.subscribe };

export function dismissNotification(id) {
  clearTimeout(timers.get(id));
  timers.delete(id);
  store.update((items) => items.filter((item) => item.id !== id));
}

export function notify(message, { title = '', kind = 'info', details = [] } = {}) {
  const id = ++nextId;
  timers.set(id, setTimeout(() => dismissNotification(id), NOTIFICATION_DURATION));
  store.update((items) => [...items, { id, message, title, kind, details }]);
  return id;
}

export function clearNotifications() {
  for (const timer of timers.values()) clearTimeout(timer);
  timers.clear();
  store.set([]);
}
