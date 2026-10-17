<script>
  import { onMount } from 'svelte';
  import Node from './Node.svelte';

  let config;
  let active;
  let values = {};
  let connected = false;
  let commandControlsEnabled = false;
  let commandBusy = false;
  let pendingControlId = null;
  let commandResults = {};
  let error = '';
  let now = Date.now();
  let socket;
  let retry;
  let stopped = false;
  let delay = 500;
  let authReady = false;
  let authEnabled = false;
  let authenticated = false;
  let username = '';
  let password = '';
  let viewerName = '';
  let busy = false;
  let configRevision = 0;

  let themeMode = 'auto';
  try {
    themeMode = localStorage.getItem('rv-theme-mode') || 'auto';
  } catch (_) {}

  let systemPrefersDark = false;
  $: effectiveTheme = themeMode === 'auto'
    ? (systemPrefersDark ? 'dark' : 'light')
    : (themeMode === 'night' ? 'dark' : 'light');

  $: if (typeof document !== 'undefined') {
    document.documentElement.setAttribute('data-theme', effectiveTheme);
  }

  function setThemeMode(mode) {
    themeMode = mode;
    try {
      localStorage.setItem('rv-theme-mode', mode);
    } catch (_) {}
  }

  function clearDashboard() {
    clearTimeout(retry);
    const previous = socket;
    socket = null;
    previous?.close();
    config = undefined;
    active = undefined;
    values = {};
    connected = false;
    commandControlsEnabled = false;
    commandBusy = false;
    pendingControlId = null;
    commandResults = {};
  }

  async function requestSession() {
    const response = await fetch('/api/auth/session', { cache: 'no-store' });
    if (!response.ok) throw new Error(`Session unavailable (${response.status})`);
    const session = await response.json();
    authEnabled = session.enabled;
    authenticated = session.authenticated;
    viewerName = session.username || '';
    authReady = true;
    return authenticated;
  }

  function applyDashboard(data) {
    config = data;
    configRevision += 1;
    error = '';
    const requested = new URLSearchParams(location.search).get('tab');
    select(data.tabs.find((tab) => tab.id === requested) || data.tabs[0]);
  }

  async function loadDashboard() {
    const response = await fetch('/api/config', { cache: 'no-store' });
    if (response.status === 401) {
      authenticated = false;
      clearDashboard();
      return;
    }
    if (!response.ok) throw new Error(`Configuration unavailable (${response.status})`);
    const data = await response.json();
    if (stopped) return;
    applyDashboard(data);
    connect();
  }

  async function signIn() {
    busy = true;
    error = '';
    try {
      const response = await fetch('/api/auth/login', {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ username, password }),
      });
      password = '';
      if (!response.ok) {
        const result = await response.json();
        throw new Error(typeof result.detail === 'string' ? result.detail : 'Login request was invalid');
      }
      await requestSession();
      await loadDashboard();
    } catch (cause) {
      password = '';
      error = cause.message;
    } finally {
      busy = false;
    }
  }

  async function signOut() {
    busy = true;
    error = '';
    try {
      const response = await fetch('/api/auth/logout', { method: 'POST' });
      if (!response.ok) throw new Error(`Logout failed (${response.status})`);
      authenticated = false;
      viewerName = '';
      clearDashboard();
    } catch (cause) {
      error = cause.message;
    } finally {
      busy = false;
    }
  }

  function select(tab) {
    // Hidden tabs should not display old values while their new snapshot is in flight.
    active = tab;
    values = {};
    const url = new URL(window.location);
    url.searchParams.set('tab', tab.id);
    history.replaceState(null, '', url);
    if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: 'subscribe', tab: tab.id }));
  }

  function sendControl(control, value) {
    if (!commandControlsEnabled || !connected || commandBusy || socket?.readyState !== WebSocket.OPEN) return;
    if (control.confirm && !window.confirm(`Send ${control.action} to ${control.target}?`)) return;
    commandBusy = true;
    pendingControlId = control.id;
    commandResults = {
      ...commandResults,
      [control.id]: { status: 'sending', message: 'Sending command...' },
    };
    const message = {
      type: 'command', action_id: control.id, confirmed: control.confirm,
    };
    if (value !== undefined) message.value = value;
    socket.send(JSON.stringify(message));
  }

  function connect() {
    if (stopped || !authenticated) return;
    const current = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws`);
    socket = current;
    socket.onopen = () => {
      if (socket !== current) return;
      connected = true;
      delay = 500;
      // The server sends the latest configuration on every connection.
    };
    socket.onmessage = (event) => {
      if (socket !== current) return;
      const message = JSON.parse(event.data);
      if (message.type === 'config') {
        applyDashboard(message.config);
        commandControlsEnabled = message.config.command_controls_enabled === true;
        return;
      }
      if (message.type === 'command_result') {
        if (pendingControlId === message.action_id) {
          commandBusy = false;
          pendingControlId = null;
        }
        commandResults = {
          ...commandResults,
          [message.action_id]: { status: message.status, message: message.message },
        };
        return;
      }
      // A snapshot replaces current-tab state; later updates merge by topic.
      if (message.type === 'snapshot') {
        if (message.tab !== active?.id) return;
        values = {};
      }
      if (message.type === 'snapshot' || message.type === 'update') {
        for (const record of message.values) values[record.topic] = record;
        // Reassign so Svelte notices changes to the topic map.
        values = { ...values };
      } else if (message.type === 'error') error = message.message;
    };
    socket.onclose = () => {
      if (socket !== current) return;
      connected = false;
      values = {};
      if (pendingControlId) {
        commandResults = {
          ...commandResults,
          [pendingControlId]: {
            status: 'failed',
            message: 'Connection closed; action outcome is unknown. Check live state before retrying.',
          },
        };
        pendingControlId = null;
        commandBusy = false;
      }
      if (!stopped) {
        // Reconnect with capped backoff; onopen subscribes to the current tab again.
        retry = setTimeout(async () => {
          try {
            if (await requestSession()) {
              error = '';
              connect();
            } else {
              clearDashboard();
              error = 'Your session ended. Please log in again.';
            }
          } catch (cause) {
            error = cause.message;
            if (!stopped) retry = setTimeout(connect, delay);
          }
        }, delay);
        delay = Math.min(delay * 2, 10000);
      }
    };
  }

  onMount(() => {
    // Detect system dark mode preference for 'auto' mode.
    const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');
    systemPrefersDark = mediaQuery.matches;
    const handleThemeChange = (event) => {
      systemPrefersDark = event.matches;
    };
    mediaQuery.addEventListener?.('change', handleThemeChange);

    // Refresh stale indicators even when a topic stops publishing.
    const ticker = setInterval(() => { now = Date.now(); }, 1000);
    requestSession().then((valid) => {
      if (valid && !stopped) return loadDashboard();
    }).catch((cause) => { error = cause.message; });
    return () => {
      stopped = true;
      mediaQuery.removeEventListener?.('change', handleThemeChange);
      clearInterval(ticker);
      clearTimeout(retry);
      socket?.close();
    };
  });
</script>

<svelte:head><title>{config?.app?.title || 'RV Control'} | Live</title></svelte:head>

<div class="shell">
  <header class="masthead">
    <div class="identity"><span class="brand-mark">RV<span>•</span></span><div><strong>{config?.app?.title || 'RV Control'}</strong><small>LIVE SYSTEMS</small></div></div>
    <div class="masthead-controls">
      <div class="theme-switch" role="group" aria-label="Display theme">
        <button type="button" class:active={themeMode === 'day'} on:click={() => setThemeMode('day')}>Day</button>
        <button type="button" class:active={themeMode === 'night'} on:click={() => setThemeMode('night')}>Night</button>
        <button type="button" class:active={themeMode === 'auto'} on:click={() => setThemeMode('auto')}>Auto</button>
      </div>
      <div class="account-actions">
        {#if authenticated}<div class="connection" class:online={connected}><span class="connection-dot"></span>{connected ? 'Live telemetry' : 'Waiting for connection'}</div>{/if}
        {#if authenticated && authEnabled}<span>{viewerName}</span><button type="button" disabled={busy} on:click={signOut}>Logout</button>{/if}
      </div>
    </div>
  </header>
  {#if config}
    <nav class="tabs" aria-label="Dashboard tabs">
      {#each config.tabs as tab (tab.id)}
        <button type="button" class:selected={active?.id === tab.id} aria-current={active?.id === tab.id ? 'page' : undefined} on:click={() => select(tab)}>{tab.label || tab.id}</button>
      {/each}
    </nav>
    <main>
      {#if active}
        <div class="page-heading"><div><div class="eyebrow">SYSTEM OVERVIEW</div><h1>{active.label || active.id}</h1></div><time>{new Date(now).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</time></div>
        <!-- Remount the tree on tab changes so chart history belongs to one tab. -->
        {#key `${configRevision}:${active.id}`}<Node node={active.root} {values} {now}
          staleAfter={config.stream?.stale_after_ms ?? 10000} theme={effectiveTheme} {connected}
          {commandControlsEnabled} {commandBusy} {commandResults} sendControl={sendControl} />{/key}
      {/if}
      {#if error}<p class="error" role="alert">{error}</p>{/if}
    </main>
  {:else if authReady && !authenticated}
    <main class="login-panel">
      <form class="card" on:submit|preventDefault={signIn}>
        <h1>Log in</h1>
        <label for="username">Username</label>
        <input id="username" name="username" autocomplete="username" required maxlength="64" bind:value={username} />
        <label for="password">Password</label>
        <input id="password" name="password" type="password" autocomplete="current-password" required maxlength="1024" bind:value={password} />
        <button type="submit" disabled={busy}>{busy ? 'Logging in...' : 'Log in'}</button>
        {#if error}<p class="error" role="alert">{error}</p>{/if}
      </form>
    </main>
  {:else}
    <main><p class="loading">Loading dashboard...</p>{#if error}<p class="error" role="alert">{error}</p>{/if}</main>
  {/if}
</div>