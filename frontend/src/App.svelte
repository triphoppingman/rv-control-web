<script>
  import { onMount } from 'svelte';
  import Node from './Node.svelte';

  let config;
  let active;
  let values = {};
  let connected = false;
  let error = '';
  let now = Date.now();
  let socket;
  let retry;
  let stopped = false;
  let delay = 500;

  function select(tab) {
    // Hidden tabs should not display old values while their new snapshot is in flight.
    active = tab;
    values = {};
    const url = new URL(window.location);
    url.searchParams.set('tab', tab.id);
    history.replaceState(null, '', url);
    if (socket?.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type: 'subscribe', tab: tab.id }));
  }

  function connect() {
    if (stopped) return;
    socket = new WebSocket(`${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws`);
    socket.onopen = () => {
      connected = true;
      delay = 500;
      if (active) socket.send(JSON.stringify({ type: 'subscribe', tab: active.id }));
    };
    socket.onmessage = (event) => {
      const message = JSON.parse(event.data);
      // A snapshot replaces current-tab state; later updates merge by topic.
      if (message.type === 'snapshot' && message.tab === active?.id) values = {};
      if (message.type === 'snapshot' || message.type === 'update') {
        for (const record of message.values) values[record.topic] = record;
        // Reassign so Svelte notices changes to the topic map.
        values = { ...values };
      } else if (message.type === 'error') error = message.message;
    };
    socket.onclose = () => {
      connected = false;
      values = {};
      if (!stopped) {
        // Reconnect with capped backoff; onopen subscribes to the current tab again.
        retry = setTimeout(connect, delay);
        delay = Math.min(delay * 2, 10000);
      }
    };
  }

  onMount(() => {
    // Refresh stale indicators even when a topic stops publishing.
    const ticker = setInterval(() => { now = Date.now(); }, 1000);
    fetch('/api/config').then((response) => {
      if (!response.ok) throw new Error(`Configuration unavailable (${response.status})`);
      return response.json();
    }).then((data) => {
      config = data;
      const requested = new URLSearchParams(location.search).get('tab');
      select(data.tabs.find((tab) => tab.id === requested) || data.tabs[0]);
      connect();
    }).catch((cause) => { error = cause.message; });
    return () => {
      stopped = true;
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
    <div class="connection" class:online={connected}><span class="connection-dot"></span>{connected ? 'Live telemetry' : 'Waiting for connection'}</div>
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
        {#key active.id}<Node node={active.root} {values} {now} staleAfter={config.stream?.stale_after_ms ?? 10000} />{/key}
      {/if}
      {#if error}<p class="error" role="alert">{error}</p>{/if}
    </main>
  {:else}
    <main><p class="loading">Loading dashboard...</p>{#if error}<p class="error" role="alert">{error}</p>{/if}</main>
  {/if}
</div>