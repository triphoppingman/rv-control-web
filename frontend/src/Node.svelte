<script>
  import Dial from './Dial.svelte';
  import Gauge from './Gauge.svelte';
  import Sparkline from './Sparkline.svelte';
  import Tank from './Tank.svelte';
  import Light from './Light.svelte';
  import Fan from './Fan.svelte';
  import Generator from './Generator.svelte';
  import Thermostat from './Thermostat.svelte';
  import Map from './Map.svelte';

  // The same component recurses through layout containers and renders leaf widgets.
  export let node;
  export let values;
  export let now;
  export let staleAfter = 10000;
  export let theme = 'light';
  export let connected = false;
  export let commandControlsEnabled = false;
  export let commandBusy = false;
  export let sendControl = () => {};

  const palette = { red: '#c6534b', amber: '#c68529', green: '#147d73', blue: '#3275a4', gray: '#788a86' };

  // Bind a widget to a nested field of one MQTT topic, including array indices.
  function extract(payload, path) {
    if (!payload || !path) return undefined;
    const parts = path.replace(/^\$\.?/, '').replace(/\[(\d+)\]/g, '.$1').split('.');
    return parts.reduce((current, part) => current?.[part], payload);
  }

  function format(value, decimals) {
    return typeof value === 'number' ? value.toLocaleString(undefined, {
      minimumFractionDigits: decimals ?? 0, maximumFractionDigits: decimals ?? 1,
    }) : String(value);
  }

  function invalidLight(value) {
    if (typeof value === 'boolean') return false;
    if (typeof value !== 'object' || value === null || Array.isArray(value)
      || typeof value.on !== 'boolean') return true;
    return value.level != null && (typeof value.level !== 'number'
      || !Number.isFinite(value.level) || value.level < 0 || value.level > 100);
  }

  function invalidGenerator(value) {
    if (typeof value !== 'object' || Array.isArray(value)) return true;
    return (value.status != null && !(typeof value.status === 'string' && value.status.trim())
      && !(typeof value.status === 'number' && Number.isFinite(value.status)))
      || (value.run_hours != null && (typeof value.run_hours !== 'number'
        || !Number.isFinite(value.run_hours) || value.run_hours < 0))
      || ['starting', 'stopping'].some((field) => value[field] != null && typeof value[field] !== 'boolean')
      || (value.starting === true && value.stopping === true);
  }

  function invalidThermostat(value) {
    if (typeof value !== 'object' || value === null || Array.isArray(value)) return true;
    return (value.mode != null && typeof value.mode !== 'string')
      || (value.fan_mode != null && typeof value.fan_mode !== 'string')
      || ['fan_speed', 'setpoint_heat_c', 'setpoint_cool_c', 'ambient_c'].some((field) =>
        value[field] != null && (typeof value[field] !== 'number' || !Number.isFinite(value[field])));
  }

  function calculateDerived(node, values, now, staleAfter) {
    const readings = node.inputs.map((input) => {
      const record = values[input.topic];
      const value = extract(record?.payload, input.payload_path);
      return {
        value,
        missing: value === undefined || value === null,
        stale: !!record && now - record.ts * 1000 > (node.stale_after_ms ?? staleAfter),
      };
    });
    const missing = readings.some((reading) => reading.missing);
    const stale = readings.some((reading) => reading.stale);
    const invalid = readings.some((reading) => !reading.missing
      && (typeof reading.value !== 'number' || !Number.isFinite(reading.value)));
    if (missing || invalid) return { value: null, missing, stale, invalid };

    const inputs = readings.map((reading) => reading.value);
    let value;
    switch (node.operation) {
      case 'sum': value = inputs.reduce((total, input) => total + input, 0); break;
      case 'difference': value = inputs[0] - inputs[1]; break;
      case 'product': value = inputs.reduce((total, input) => total * input, 1); break;
      case 'ratio': value = inputs[0] / inputs[1]; break;
      case 'average': value = inputs.reduce((total, input) => total + input, 0) / inputs.length; break;
      default: return { value: null, missing, stale, invalid: true };
    }
    return Number.isFinite(value)
      ? { value, missing, stale, invalid: false }
      : { value: null, missing, stale, invalid: true };
  }

  // Svelte recomputes these states as telemetry or the shared clock changes.
  $: record = values[node.topic];
  $: derived = node.type === 'derived' ? calculateDerived(node, values, now, staleAfter) : null;
  $: value = node.type === 'derived' ? derived.value : extract(record?.payload, node.payload_path);
  $: missing = node.type === 'derived' ? derived.missing
    : node.type === 'thermostat' ? value == null || (
      typeof value === 'object' && !Array.isArray(value)
        && ['mode', 'fan_mode', 'fan_speed', 'setpoint_heat_c', 'setpoint_cool_c', 'ambient_c']
          .every((field) => value[field] == null)
    ) : value === undefined || value === null
      || (node.type === 'generator' && typeof value === 'object' && !Array.isArray(value)
        && ['status', 'run_hours', 'starting', 'stopping'].every((field) => value[field] == null));
  $: lidRecord = node.type === 'fan' && node.lid_topic ? values[node.lid_topic] : null;
  $: lid = extract(lidRecord?.payload, node.lid_payload_path);
  $: lidStale = !!lidRecord && now - lidRecord.ts * 1000 > (node.stale_after_ms ?? staleAfter);
  $: stale = node.type === 'derived' ? derived.stale : !missing && now - record.ts * 1000 > (node.stale_after_ms ?? staleAfter);
  $: invalid = node.type === 'derived' ? derived.invalid : !missing && (
    node.type === 'thermostat' ? invalidThermostat(value)
      : node.type === 'generator' ? invalidGenerator(value) : node.type === 'light' ? invalidLight(value) : node.type === 'fan'
      ? typeof value !== 'boolean' && (typeof value !== 'object' || Array.isArray(value) || typeof value.on !== 'boolean')
      : node.type === 'tank'
      && (typeof value !== 'number' || !Number.isFinite(value)));
  // The highest threshold at or below the reading determines its color.
  $: active = node.thresholds?.filter((threshold) => Number(value) >= threshold.at)
    .sort((left, right) => right.at - left.at)[0];
  $: accent = palette[active?.color] || active?.color || '#147d73';
  $: state = missing ? 'No data' : invalid ? 'Invalid input' : stale ? 'Stale' : 'Live';
</script>

{#if node.visible !== false}
  {#if ['grid', 'row', 'column', 'stack', 'card', 'flow'].includes(node.type)}
    <div class="node {node.type} {node.class || ''}" style="--cols:{node.cols || 12}; --gap:{node.gap ?? 16}px; --span:{node.span || 12}; --min-width:{node.min_width || 'auto'}">
      {#if node.type === 'card' && (node.title || node.subtitle)}
        <header class="card-header"><h2>{node.title}</h2>{#if node.subtitle}<p>{node.subtitle}</p>{/if}</header>
      {/if}
      {#each node.children || [] as child, index (child.id || index)}
        <svelte:self node={child} {values} {now} {staleAfter} {theme}
          {connected} {commandControlsEnabled} {commandBusy} {sendControl} />
      {/each}
    </div>
  {:else if ['numeric', 'boolean', 'gauge', 'dial', 'sparkline', 'derived', 'tank', 'light', 'fan', 'generator', 'thermostat'].includes(node.type)}
    <div class="widget {node.type}" class:stale style="--accent:{accent}; --span:{node.span || 12}; --min-width:{node.min_width || 'auto'}">
      <div class="widget-top"><span class="widget-label">{node.label || node.payload_path || node.operation}</span><span class="state" class:offline={missing || stale || invalid}>{state}</span></div>
      {#if node.type === 'generator'}
        <Generator value={missing || invalid ? null : value} controls={node.controls || []}
          stateFresh={!missing && !invalid && !stale} controlsEnabled={commandControlsEnabled}
          {connected} {commandBusy} {sendControl} />
      {:else if node.type === 'thermostat'}
        <Thermostat value={missing || invalid ? null : value} controls={node.controls || []}
          stateFresh={!missing && !invalid && !stale} controlsEnabled={commandControlsEnabled}
          {connected} {commandBusy} {sendControl} />
      {:else if node.type === 'fan'}
        <Fan value={missing || invalid ? null : value} showLid={!!node.lid_topic} {lid} {lidStale}
          stateFresh={!missing && !invalid && !stale} controls={node.controls || []}
          controlsEnabled={commandControlsEnabled} {connected} {commandBusy} {sendControl} />
      {:else if node.type === 'light'}
        <Light value={missing || invalid ? null : value} label={node.label || 'Light'}
          controls={node.controls || []} controlsEnabled={commandControlsEnabled}
          {connected} {commandBusy} sendControl={sendControl} />
      {:else if node.type === 'boolean'}
        <div class="boolean-value" class:on={!missing && (node.on_when === undefined ? !!value : value === node.on_when)}>
          <span class="indicator"></span>{missing ? '--' : (node.on_when === undefined ? !!value : value === node.on_when) ? (node.true_label || 'On') : (node.false_label || 'Off')}
        </div>
      {:else}
        {#if node.type === 'dial'}
          <Dial value={missing ? null : Number(value)} min={node.min ?? 0} max={node.max ?? 100}
            {theme} lowWarningBelow={node.low_warning_below ?? null}
            showWarning={node.show_warning ?? true} />
        {:else if node.type === 'gauge'}
          <Gauge value={missing ? null : Number(value)} min={node.min ?? 0} max={node.max ?? 100}
            color={accent} {theme} />
        {:else if node.type === 'tank'}
          <Tank value={missing || invalid ? null : value} min={node.min ?? 0} max={node.max ?? 100}
            segments={node.segments ?? 3} label={node.label || node.payload_path} />
        {:else if node.type === 'sparkline'}
          <Sparkline value={missing ? null : Number(value)} min={node.min ?? 0} max={node.max ?? 100} color={accent}
            {theme}
            historyPoints={node.history_points ?? 60} sampleIntervalMs={node.sample_interval_ms ?? 1000}
            timestamp={record?.ts == null ? null : record.ts * 1000} />
        {/if}
        <div class="reading">{missing || invalid ? '--' : format(value, node.decimals)}{#if node.unit}<small>{node.unit}</small>{/if}</div>
      {/if}
      {#if node.controls?.length && !['light', 'fan', 'generator', 'thermostat'].includes(node.type)}
        <div class="control-actions" aria-label={`${node.label || 'Entity'} controls`}>
          {#each node.controls as control (control.id)}
            <button type="button" disabled={!commandControlsEnabled || !connected || commandBusy}
              title={!commandControlsEnabled ? 'Controls are disabled by server configuration' : undefined}
              on:click={() => sendControl(control)}>{control.label}</button>
          {/each}
        </div>
      {/if}
    </div>
  {:else if node.type === 'map'}
    <Map {node} {values} {now} {staleAfter} />
  {:else if node.type === 'text'}
    <div class="text {node.variant || 'body'}" style="--span:{node.span || 12}">{node.content}</div>
  {:else if node.type === 'image'}
    <img class="static-image" src="/assets/{node.src}" alt={node.alt || ''} style="height:{node.height || 'auto'}; object-fit:{node.fit || 'contain'}; --span:{node.span || 12}" />
  {:else if node.type === 'divider'}
    <hr class="divider" style="--span:{node.span || 12}" />
  {:else if node.type === 'spacer'}
    <div class="spacer" style="height:{node.size || '16px'}; --span:{node.span || 12}"></div>
  {:else if node.type === 'icon'}
    <span class="static-icon" aria-label={node.label || node.name} style="--span:{node.span || 12}">{node.name || '●'}</span>
  {/if}
{/if}