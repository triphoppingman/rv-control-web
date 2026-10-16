<script>
  import Dial from './Dial.svelte';
  import Gauge from './Gauge.svelte';
  import Sparkline from './Sparkline.svelte';
  import Tank from './Tank.svelte';
  import Map from './Map.svelte';

  // The same component recurses through layout containers and renders leaf widgets.
  export let node;
  export let values;
  export let now;
  export let staleAfter = 10000;
  export let theme = 'light';

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
  $: missing = node.type === 'derived' ? derived.missing : value === undefined || value === null;
  $: stale = node.type === 'derived' ? derived.stale : !missing && now - record.ts * 1000 > (node.stale_after_ms ?? staleAfter);
  $: invalid = node.type === 'derived' ? derived.invalid : node.type === 'tank' && !missing
    && (typeof value !== 'number' || !Number.isFinite(value));
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
        <svelte:self node={child} {values} {now} {staleAfter} {theme} />
      {/each}
    </div>
  {:else if ['numeric', 'boolean', 'gauge', 'dial', 'sparkline', 'derived', 'tank'].includes(node.type)}
    <div class="widget {node.type}" class:stale style="--accent:{accent}; --span:{node.span || 12}; --min-width:{node.min_width || 'auto'}">
      <div class="widget-top"><span class="widget-label">{node.label || node.payload_path || node.operation}</span><span class="state" class:offline={missing || stale || invalid}>{state}</span></div>
      {#if node.type === 'boolean'}
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