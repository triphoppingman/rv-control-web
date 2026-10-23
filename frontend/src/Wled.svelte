<script>
  export let value = null;
  export let label = 'WLED';
  export let controls = [];
  export let controlsEnabled = false;
  export let stateFresh = false;
  export let connected = false;
  export let commandBusy = false;
  export let sendControl = () => {};

  let sliderValues = {};
  let formValues = {};
  $: disabled = !controlsEnabled || !stateFresh || !connected || commandBusy;
  $: toggleControl = controls.find((control) => control.action === 'toggle');
  $: actionControls = controls.filter((control) =>
    control !== toggleControl && !control.input);
  $: sliderControls = controls.filter((control) => control.input?.type === 'slider');
  $: formControls = controls.filter((control) => control.input?.type === 'form');

  $: brightness = typeof value?.bri === 'number' ? Math.round(value.bri / 255 * 100) : null;
  $: segments = Array.isArray(value?.seg) ? value.seg : [];
  $: visibleSegments = segments.slice(0, 4);
  $: hiddenSegments = Math.max(0, segments.length - visibleSegments.length);
  $: activeSegments = value?.on
    ? segments.filter((segment) => segment.on !== false).length : 0;

  function color(segment) {
    const rgb = Array.isArray(segment.col?.[0]) ? segment.col[0] : segment.col;
    return Array.isArray(rgb) && rgb.length >= 3
      ? `rgb(${rgb[0]}, ${rgb[1]}, ${rgb[2]})` : null;
  }

  function sliderReading(control, state) {
    return state?.[control.input.value_field || control.input.param];
  }

  function submitSlider(control, event) {
    sendControl(control, Number(event.currentTarget.value));
    sliderValues = {};
  }

  function fieldValue(control, field) {
    return formValues[control.id]?.[field.param] ?? field.min;
  }

  function updateField(control, field, event) {
    formValues = { ...formValues, [control.id]: {
      ...formValues[control.id],
      [field.param]: event.currentTarget.value === '' ? '' : Number(event.currentTarget.value),
    } };
  }

  function submitForm(control) {
    sendControl(control, Object.fromEntries(control.input.fields.map((field) =>
      [field.param, fieldValue(control, field)])));
  }
</script>

<section class="wled-state" aria-label="WLED state">
  <div class="wled-overview">
    {#if toggleControl}
      <button type="button" class="wled-status" class:on={value?.on}
        aria-label={`Toggle ${label}`} {disabled} on:click={() => sendControl(toggleControl)}>
        <span class="wled-status-dot"></span>{value?.on == null ? '--' : value.on ? 'On' : 'Off'}
      </button>
    {:else}
      <div class="wled-status" class:on={value?.on}>
        <span class="wled-status-dot"></span>{value?.on == null ? '--' : value.on ? 'On' : 'Off'}
      </div>
    {/if}
    <div class="wled-brightness">
      <div class="wled-brightness-label">
        <span>Brightness</span>
        <strong>{brightness == null ? '--' : `${brightness}%`}</strong>
      </div>
      <div class="wled-brightness-track" role="meter" aria-label="WLED brightness"
        aria-valuemin="0" aria-valuemax="100"
        aria-valuenow={brightness == null ? undefined : brightness}>
        <span style:width="{brightness ?? 0}%"></span>
      </div>
    </div>
    <div class="wled-segment-summary">
      {segments.length} {segments.length === 1 ? 'segment' : 'segments'}
      {#if segments.length} · {activeSegments} active{/if}
    </div>
  </div>

  {#each sliderControls as control (control.id)}
    <label class="wled-slider">
      <span>{control.label}: {sliderValues[control.id] ?? sliderReading(control, value) ?? '--'}{control.input.unit || ''}</span>
      <input type="range" min={control.input.min} max={control.input.max} step={control.input.step}
        value={sliderValues[control.id] ?? sliderReading(control, value) ?? control.input.min}
        aria-label={`${label} ${control.label}`}
        disabled={disabled || sliderReading(control, value) == null}
        on:input={(event) => sliderValues = { ...sliderValues, [control.id]: Number(event.currentTarget.value) }}
        on:change={(event) => submitSlider(control, event)} />
    </label>
  {/each}
  {#if actionControls.length}
    <div class="wled-actions" role="group" aria-label={`${label} actions`}>
      {#each actionControls as control (control.id)}
        <button type="button" {disabled} on:click={() => sendControl(control)}>{control.label}</button>
      {/each}
    </div>
  {/if}

  {#each formControls as control (control.id)}
    <form class="wled-form" aria-label={`${label} ${control.label}`}
      on:submit|preventDefault={() => submitForm(control)}>
      <fieldset {disabled}>
        <legend>{control.label}</legend>
        {#each control.input.fields as field (field.param)}
          <label>
            <span>{field.label}</span>
            <input type="number" name={field.param} min={field.min} max={field.max} step={field.step}
              value={formValues[control.id]?.[field.param] ?? field.min} required
              on:input={(event) => updateField(control, field, event)} />
          </label>
        {/each}
        <button type="submit">Apply {control.label}</button>
      </fieldset>
    </form>
  {/each}

  {#if visibleSegments.length}
    <ul class="wled-segments" aria-label="WLED segments">
      {#each visibleSegments as segment, index (segment.id ?? index)}
        <li class:inactive={segment.on === false}>
          <span class="wled-color" role="img"
            aria-label={color(segment) ? `Color ${color(segment)}` : 'Color unavailable'}
            style:background-color={color(segment) || 'transparent'}></span>
          <strong>Seg {segment.id ?? index + 1}</strong>
          <span>FX {segment.fx ?? '--'}</span>
          <span>Pal {segment.pal ?? '--'}</span>
        </li>
      {/each}
      {#if hiddenSegments}
        <li class="wled-more">+{hiddenSegments} more</li>
      {/if}
    </ul>
  {/if}
</section>

<style>
  .wled-state { display: grid; gap: 14px; margin-top: 16px; }
  .wled-overview { display: grid; grid-template-columns: auto minmax(110px, 1fr) auto; align-items: center; gap: 16px; }
  .wled-status { display: inline-flex; align-items: center; gap: 7px; color: var(--color-text-muted); font-size: 13px; font-weight: 600; }
  .wled-status.on { color: var(--accent, #147d73); }
  button.wled-status { border: 0; padding: 0; background: transparent; font-family: inherit; cursor: pointer; }
  .wled-actions { display: flex; flex-wrap: wrap; gap: 8px; }
  .wled-actions button, .wled-form button { cursor: pointer; border: 1px solid var(--border-widget); border-radius: 4px; padding: 7px 10px; background: var(--bg-card); color: var(--color-text); font: 600 12px 'DM Sans', sans-serif; }
  .wled-form fieldset { display: flex; flex-wrap: wrap; align-items: end; gap: 8px; min-width: 0; margin: 0; padding: 10px; border: 1px solid var(--border-widget); border-radius: 6px; }
  .wled-form legend { color: var(--color-text); font-size: 12px; }
  .wled-form label { display: grid; gap: 4px; color: var(--color-text-muted); font-size: 11px; }
  .wled-form input { box-sizing: border-box; width: 90px; padding: 6px; border: 1px solid var(--border-widget); border-radius: 4px; background: var(--bg-card); color: var(--color-text); }
  .wled-form fieldset:disabled { opacity: 0.6; }
  .wled-actions button:hover { border-color: var(--accent, #147d73); }
  button:disabled { cursor: not-allowed; opacity: 0.6; }
  .wled-slider { display: grid; grid-template-columns: auto minmax(90px, 1fr); align-items: center; gap: 12px; color: var(--color-text-muted); font-size: 12px; }
  .wled-slider input { width: 100%; accent-color: var(--accent, #147d73); }
  .wled-status-dot { width: 9px; height: 9px; border-radius: 50%; background: currentColor; box-shadow: 0 0 10px color-mix(in srgb, currentColor 45%, transparent); }
  .wled-brightness { display: grid; gap: 6px; min-width: 0; }
  .wled-brightness-label { display: flex; justify-content: space-between; gap: 8px; color: var(--color-text-muted); font-size: 11px; }
  .wled-brightness-label strong { color: var(--color-reading); font: 600 12px 'DM Sans', sans-serif; }
  .wled-brightness-track { height: 6px; overflow: hidden; border-radius: 999px; background: var(--border-widget); }
  .wled-brightness-track span { display: block; height: 100%; border-radius: inherit; background: var(--accent, #147d73); transition: width 180ms ease; }
  .wled-segment-summary { color: var(--color-text-muted); font-size: 11px; white-space: nowrap; }
  .wled-segments { display: grid; grid-template-columns: repeat(auto-fit, minmax(145px, 1fr)); gap: 7px; margin: 0; padding: 0; list-style: none; }
  .wled-segments li { display: flex; align-items: center; gap: 7px; min-width: 0; padding: 7px 8px; border: 1px solid var(--border-widget); border-radius: 6px; color: var(--color-text-muted); font-size: 10px; }
  .wled-segments li strong { color: var(--color-text); font: 600 10px 'DM Sans', sans-serif; }
  .wled-segments li.inactive { opacity: 0.5; }
  .wled-color { width: 12px; height: 12px; flex: none; border: 1px solid var(--border-widget); border-radius: 50%; }
  .wled-more { justify-content: center; }
  @media (max-width: 420px) {
    .wled-overview { grid-template-columns: auto minmax(90px, 1fr); gap: 10px; }
    .wled-segment-summary { grid-column: 1 / -1; }
  }
</style>
