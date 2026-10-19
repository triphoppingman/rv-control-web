<script>
  export let value = null;
  export let label = 'Light';
  export let controls = [];
  export let controlsEnabled = false;
  export let connected = false;
  export let commandBusy = false;
  export let sendControl = () => {};

  $: on = typeof value === 'boolean' ? value : value?.on;
  $: level = typeof value === 'object' && value !== null ? value.level : null;
  $: valid = typeof on === 'boolean'
    && (level == null || (typeof level === 'number' && Number.isFinite(level) && level >= 0 && level <= 100));
  $: brightness = valid && on ? (level ?? 100) : 0;
  $: toggleControl = controls.find((control) => control.action === 'toggle');
  $: sliderControls = controls.filter((control) => control.input?.type === 'slider');
  $: sliderReadings = Object.fromEntries(sliderControls.map((control) => {
    const reported = control.input.value_field ? value?.[control.input.value_field] : level;
    return [control.id, typeof reported === 'number' && Number.isFinite(reported)
      ? reported : control.input.max];
  }));
  $: menuControls = controls.filter((control) => control.action !== 'toggle' && control.input?.type !== 'slider');
  let menuOpen = false;
  let controlRoot;
  let sliderValues = {};

  function openMenu(event) {
    if (menuControls.length) {
      event.preventDefault();
      menuOpen = true;
    }
  }

  function run(control, value) {
    menuOpen = false;
    sendControl(control, value);
  }

  function setSliderValue(control, event) {
    sliderValues = { ...sliderValues, [control.id]: Number(event.currentTarget.value) };
  }

  function submitSlider(control) {
    run(control, sliderValues[control.id]);
  }

  function dismissMenu(event) {
    if (event.key === 'Escape' || !controlRoot?.contains(event.target)) menuOpen = false;
  }
</script>

<svelte:window on:keydown={dismissMenu} on:click={dismissMenu} />

<div bind:this={controlRoot} class="light-control" role="group" aria-label={`${label} controls`}
  on:contextmenu={openMenu}>
  {#if toggleControl}
    <button type="button" class="light-status" class:on={valid && on}
      aria-label={`Toggle ${label}`} title={`Click to toggle ${label}; right-click for other actions`}
      disabled={!controlsEnabled || !connected || commandBusy}
      on:click={() => run(toggleControl)}>
      <svg class="bulb" viewBox="0 0 48 56" aria-hidden="true">
        <path class="bulb-fill" style="fill-opacity:{valid ? 0.15 + brightness / 100 * 0.85 : 0}"
          d="M24 4a16 16 0 0 0-10 28c3 2 4 5 4 8h12c0-3 1-6 4-8A16 16 0 0 0 24 4Z" />
        <path d="M24 4a16 16 0 0 0-10 28c3 2 4 5 4 8h12c0-3 1-6 4-8A16 16 0 0 0 24 4ZM18 46h12M21 52h6" />
      </svg>
      <span class="light-reading">
        <strong>{valid ? (on ? 'On' : 'Off') : '--'}</strong>
        {#if valid && on && level != null}
          <span class="brightness">{level.toLocaleString(undefined, { maximumFractionDigits: 1 })}% brightness</span>
        {/if}
      </span>
    </button>
  {:else}
    <div class="light-status" class:on={valid && on}>
      <svg class="bulb" viewBox="0 0 48 56" aria-hidden="true">
        <path class="bulb-fill" style="fill-opacity:{valid ? 0.15 + brightness / 100 * 0.85 : 0}"
          d="M24 4a16 16 0 0 0-10 28c3 2 4 5 4 8h12c0-3 1-6 4-8A16 16 0 0 0 24 4Z" />
        <path d="M24 4a16 16 0 0 0-10 28c3 2 4 5 4 8h12c0-3 1-6 4-8A16 16 0 0 0 24 4ZM18 46h12M21 52h6" />
      </svg>
      <div class="light-reading">
        <strong>{valid ? (on ? 'On' : 'Off') : '--'}</strong>
        {#if valid && on && level != null}
          <span class="brightness">{level.toLocaleString(undefined, { maximumFractionDigits: 1 })}% brightness</span>
        {/if}
      </div>
    </div>
  {/if}
  {#if menuControls.length}
    <div class="light-action-menu">
      <button type="button" class="light-menu-trigger" aria-haspopup="menu"
        aria-expanded={menuOpen} disabled={!controlsEnabled || !connected || commandBusy}
        on:click={() => menuOpen = !menuOpen}>Actions</button>
      {#if menuOpen}
        <div class="light-menu" role="menu" aria-label={`${label} actions`}>
          {#each menuControls as control (control.id)}
            <button type="button" role="menuitem" disabled={!controlsEnabled || !connected || commandBusy}
              on:click={() => run(control)}>{control.label}</button>
          {/each}
        </div>
      {/if}
    </div>
  {/if}
</div>
{#each sliderControls as control (control.id)}
  <label class="light-dimmer">
    <span>{control.label}: {sliderValues[control.id] ?? sliderReadings[control.id]}{control.input.unit || ''}</span>
    <input type="range" min={control.input.min} max={control.input.max} step={control.input.step}
      value={sliderValues[control.id] ?? sliderReadings[control.id]}
      aria-label={`${label} ${control.label}`}
      disabled={!controlsEnabled || !connected || commandBusy}
      on:input={(event) => setSliderValue(control, event)}
      on:change={() => submitSlider(control)} />
  </label>
{/each}

<style>
  .light-control { display: flex; align-items: center; gap: 12px; margin-top: 18px; position: relative; }
  .light-status { display: flex; align-items: center; gap: 16px; color: var(--color-text-muted); text-align: left; border: 0; padding: 0; background: transparent; font: inherit; }
  button.light-status { cursor: pointer; }
  button.light-status:disabled { cursor: wait; }
  .light-status.on { color: var(--accent, #147d73); }
  .bulb { width: 48px; height: 56px; flex: none; fill: none; stroke: currentColor; stroke-width: 2.5; stroke-linecap: round; stroke-linejoin: round; }
  .bulb-fill { fill: currentColor; stroke: none; }
  .light-reading { display: flex; flex-direction: column; gap: 4px; }
  strong { font: 600 26px 'Space Grotesk', sans-serif; }
  .brightness { font-size: 12px; color: var(--color-text-muted); }
  .light-action-menu { margin-left: auto; position: relative; }
  .light-menu-trigger, .light-menu button { cursor: pointer; border: 1px solid var(--border-widget); border-radius: 4px; padding: 7px 10px; background: var(--bg-card); color: var(--color-text); font: 600 12px 'DM Sans', sans-serif; }
  .light-menu { position: absolute; z-index: 10; top: calc(100% + 5px); right: 0; display: grid; min-width: 130px; gap: 4px; padding: 6px; border: 1px solid var(--border-widget); border-radius: 4px; background: var(--bg-card); box-shadow: 0 6px 18px #0003; }
  .light-menu button { text-align: left; }
  .light-menu button:hover, .light-menu-trigger:hover { border-color: var(--accent, #147d73); }
  .light-dimmer { display: grid; grid-template-columns: auto minmax(100px, 1fr); align-items: center; gap: 12px; margin-top: 12px; color: var(--color-text-muted); font-size: 12px; }
  .light-dimmer input { width: 100%; accent-color: var(--accent, #147d73); }
  :global(.stale) .light-status { opacity: 0.55; }
</style>
