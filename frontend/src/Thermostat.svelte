<script>
  export let value = null;
  export let temperatureUnit = 'F';
  export let controls = [];
  export let stateFresh = false;
  export let controlsEnabled = false;
  export let connected = false;
  export let commandBusy = false;
  export let sendControl = () => {};

  $: mode = value?.mode;
  $: modeControls = controls.filter((control) => ['cool', 'heat', 'auto', 'off'].includes(control.action));
  $: fanControls = controls.filter((control) => ['fan_auto', 'fan_high', 'fan_low'].includes(control.action));
  $: setpointDown = controls.find((control) => control.action === 'setpoint_down');
  $: setpointUp = controls.find((control) => control.action === 'setpoint_up');
  $: activeSetpoint = mode === 'heat' ? value?.setpoint_heat_c
    : mode === 'auto' ? null : value?.setpoint_cool_c;
  $: hasSetpoint = typeof value?.setpoint_heat_c === 'number'
    || typeof value?.setpoint_cool_c === 'number';
  $: enabled = controlsEnabled && connected && stateFresh && !commandBusy;

  function temperature(value) {
    if (typeof value !== 'number' || !Number.isFinite(value)) return '--';
    const displayed = temperatureUnit === 'C' ? value : value * 9 / 5 + 32;
    return `${displayed.toFixed(1)} °${temperatureUnit}`;
  }

  function modeSelected(action) {
    return action === mode || (action === 'off' && mode === 'off');
  }
</script>

<div class="thermostat-readings">
  <div class="thermostat-temperature">
    <span>Environment</span>
    <strong>{temperature(value?.ambient_c)}</strong>
  </div>
  <div class="thermostat-temperature">
    <span>Fan status</span>
    <strong>{value?.fan_mode === 'auto' ? 'Auto' : value?.fan_mode === 'on' ? 'On' : '--'}</strong>
  </div>
</div>

{#if modeControls.length}
  <div class="thermostat-control-group" role="group" aria-label="Operating mode">
    {#each modeControls as control (control.id)}
      <button type="button" aria-pressed={modeSelected(control.action)} disabled={!enabled}
        on:click={() => sendControl(control)}>{control.label}</button>
    {/each}
  </div>
{/if}

{#if fanControls.length}
  <div class="thermostat-control-group" role="group" aria-label="Fan speed">
    {#each fanControls as control (control.id)}
      <button type="button" aria-pressed={control.action === 'fan_auto' && value?.fan_mode === 'auto'}
        disabled={!enabled} on:click={() => sendControl(control)}>{control.label}</button>
    {/each}
  </div>
{/if}

{#if setpointDown || setpointUp}
  <div class="thermostat-setpoint">
    <span>{mode === 'heat' ? 'Heat set point' : mode === 'auto' ? 'Heat / Cool set points' : 'Cool set point'}</span>
    <strong>{mode === 'auto'
      ? `${temperature(value?.setpoint_heat_c)} / ${temperature(value?.setpoint_cool_c)}`
      : temperature(activeSetpoint)}</strong>
    <div class="thermostat-setpoint-controls" role="group" aria-label="Adjust set point">
      {#if setpointDown}
        <button type="button" aria-label={setpointDown.label}
          disabled={!enabled || !hasSetpoint} on:click={() => sendControl(setpointDown)}>−</button>
      {/if}
      {#if setpointUp}
        <button type="button" aria-label={setpointUp.label}
          disabled={!enabled || !hasSetpoint} on:click={() => sendControl(setpointUp)}>+</button>
      {/if}
    </div>
  </div>
{/if}


<style>
  .thermostat-readings { display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 12px; margin-top: 16px; }
  .thermostat-temperature { display: grid; gap: 4px; }
  .thermostat-temperature span, .thermostat-setpoint > span { color: var(--color-text-muted); font-size: 11px; }
  .thermostat-temperature strong, .thermostat-setpoint > strong { color: var(--color-reading); font: 600 20px 'Space Grotesk', sans-serif; }
  .thermostat-control-group { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 14px; }
  .thermostat-control-group button, .thermostat-setpoint-controls button { cursor: pointer; border: 1px solid var(--border-widget); border-radius: 4px; padding: 7px 12px; background: var(--bg-card); color: var(--color-text); font: 600 12px 'DM Sans', sans-serif; }
  .thermostat-control-group button[aria-pressed='true'] { border-color: var(--accent, #147d73); color: var(--accent, #147d73); }
  .thermostat-control-group button:hover:not(:disabled), .thermostat-setpoint-controls button:hover:not(:disabled) { border-color: var(--accent, #147d73); }
  .thermostat-control-group button:disabled, .thermostat-setpoint-controls button:disabled { cursor: wait; opacity: 0.55; }
  .thermostat-setpoint { display: flex; align-items: center; flex-wrap: wrap; gap: 12px; margin-top: 16px; }
  .thermostat-setpoint-controls { display: flex; gap: 6px; margin-left: auto; }
  .thermostat-setpoint-controls button { min-width: 38px; font-size: 18px; }
</style>
