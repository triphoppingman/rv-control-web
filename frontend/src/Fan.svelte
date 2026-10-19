<script>
  export let value = null;
  export let showLid = false;
  export let lid = null;
  export let lidStale = false;
  export let stateFresh = false;
  export let controls = [];
  export let controlsEnabled = false;
  export let connected = false;
  export let commandBusy = false;
  export let sendControl = () => {};

  $: on = typeof value === 'boolean' ? value : value?.on;
  $: valid = typeof on === 'boolean';
  $: fanControl = !stateFresh || !valid ? null
    : controls.find((control) => control.action === (on ? 'off' : 'on'));
  $: lidMissing = lid == null || (typeof lid === 'object' && !Array.isArray(lid)
    && (lid.open_active == null || lid.close_active == null));
  $: lidInvalid = !lidMissing && (typeof lid !== 'object' || Array.isArray(lid)
    || typeof lid.open_active !== 'boolean' || typeof lid.close_active !== 'boolean'
    || (lid.open_active && lid.close_active)
    || ['open_remaining', 'close_remaining'].some((field) => lid[field] != null
      && (typeof lid[field] !== 'number' || !Number.isFinite(lid[field]) || lid[field] < 0)));
  $: lidStatus = lidMissing ? 'No data' : lidInvalid ? 'Invalid input'
    : lid.open_active ? 'Raising' : lid.close_active ? 'Lowering' : 'Idle';
  $: remaining = lidMissing || lidInvalid ? null
    : lid.open_active ? lid.open_remaining : lid.close_active ? lid.close_remaining : null;
  $: lidIdle = showLid && !lidStale && !lidMissing && !lidInvalid
    && !lid.open_active && !lid.close_active;
  $: lidControls = lidIdle
    ? controls.filter((control) => control.action === 'open' || control.action === 'close') : [];
</script>

<div class="fan-status" class:on={valid && on}>
  <svg viewBox="0 0 48 48" aria-hidden="true">
    <circle cx="24" cy="24" r="21" fill="none" />
    <path d="M24 21C10 20 11 5 20 8c5 2 5 8 4 13ZM27 24c1-14 16-13 13-4-2 5-8 5-13 4ZM24 27c14 1 13 16 4 13-5-2-5-8-4-13ZM21 24C20 38 5 37 8 28c2-5 8-5 13-4Z" />
    <circle cx="24" cy="24" r="4" />
  </svg>
  <strong>{valid ? (on ? 'On' : 'Off') : '--'}</strong>
</div>
{#if showLid}
  <div class="fan-lid" class:stale={lidStale}>
    <span>Lid: {lidStatus}</span>
    {#if remaining != null}<span class="lid-remaining">{remaining}s remaining (reported)</span>{/if}
    {#if lidStale}<span class="state offline">Stale</span>{/if}
  </div>
{/if}
{#if fanControl}
  <button type="button" class="fan-action" disabled={!controlsEnabled || !connected || commandBusy}
    title={!controlsEnabled ? 'Controls are disabled by server configuration' : undefined}
    on:click={() => sendControl(fanControl)}>{fanControl.action === 'on' ? 'Start' : 'Stop'}</button>
{/if}
{#if lidControls.length}
  <div class="fan-lid-actions" aria-label="Kitchen fan lid controls">
    {#each lidControls as control (control.id)}
      <button type="button" class="fan-action" disabled={!controlsEnabled || !connected || commandBusy}
        title={!controlsEnabled ? 'Controls are disabled by server configuration' : undefined}
        on:click={() => sendControl(control)}>{control.label}</button>
    {/each}
  </div>
{/if}

<style>
  .fan-status { display: flex; align-items: center; gap: 16px; margin-top: 18px; color: var(--color-text-muted); }
  .fan-status.on { color: var(--accent, #147d73); }
  svg { width: 48px; height: 48px; flex: none; fill: currentColor; stroke: currentColor; stroke-width: 1.5; }
  strong { font: 600 26px 'Space Grotesk', sans-serif; }
  .fan-lid { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; margin-top: 14px; color: var(--color-text-muted); font-size: 12px; }
  .fan-action { cursor: pointer; border: 1px solid var(--border-widget); border-radius: 4px; padding: 8px 14px; background: var(--bg-card); color: var(--color-text); font: 600 13px 'DM Sans', sans-serif; }
  .fan-action:hover { border-color: var(--accent, #147d73); }
  .fan-action:disabled { cursor: wait; opacity: 0.6; }
  .fan-lid-actions { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }
  .fan-lid.stale, :global(.widget.stale) .fan-status { opacity: 0.55; }
</style>
