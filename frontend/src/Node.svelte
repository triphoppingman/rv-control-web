<script>
  import Chart from './Chart.svelte';

  // The same component recurses through layout containers and renders leaf widgets.
  export let node;
  export let values;
  export let now;
  export let staleAfter = 10000;

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

  // Svelte recomputes these states as telemetry or the shared clock changes.
  $: record = values[node.topic];
  $: value = extract(record?.payload, node.payload_path);
  $: missing = value === undefined || value === null;
  $: stale = !missing && now - record.ts * 1000 > (node.stale_after_ms ?? staleAfter);
  // The highest threshold at or below the reading determines its color.
  $: active = node.thresholds?.filter((threshold) => Number(value) >= threshold.at)
    .sort((left, right) => right.at - left.at)[0];
  $: accent = palette[active?.color] || active?.color || '#147d73';
  $: state = missing ? 'No data' : stale ? 'Stale' : 'Live';
</script>

{#if node.visible !== false}
  {#if ['grid', 'row', 'column', 'stack', 'card'].includes(node.type)}
    <div class="node {node.type} {node.class || ''}" style="--cols:{node.cols || 12}; --gap:{node.gap ?? 16}px; --span:{node.span || 12}; --min-width:{node.min_width || 'auto'}">
      {#if node.type === 'card' && (node.title || node.subtitle)}
        <header class="card-header"><h2>{node.title}</h2>{#if node.subtitle}<p>{node.subtitle}</p>{/if}</header>
      {/if}
      {#each node.children || [] as child, index (child.id || index)}
        <svelte:self node={child} {values} {now} {staleAfter} />
      {/each}
    </div>
  {:else if ['numeric', 'boolean', 'gauge', 'dial', 'sparkline'].includes(node.type)}
    <div class="widget {node.type}" class:stale style="--accent:{accent}; --span:{node.span || 12}; --min-width:{node.min_width || 'auto'}">
      <div class="widget-top"><span class="widget-label">{node.label || node.payload_path}</span><span class="state" class:offline={missing || stale}>{state}</span></div>
      {#if node.type === 'boolean'}
        <div class="boolean-value" class:on={!missing && (node.on_when === undefined ? !!value : value === node.on_when)}>
          <span class="indicator"></span>{missing ? '--' : (node.on_when === undefined ? !!value : value === node.on_when) ? (node.true_label || 'On') : (node.false_label || 'Off')}
        </div>
      {:else}
        {#if ['gauge', 'dial', 'sparkline'].includes(node.type)}
          <Chart type={node.type} value={missing ? null : Number(value)} min={node.min ?? 0} max={node.max ?? 100} color={accent} />
        {/if}
        <div class="reading">{missing ? '--' : format(value, node.decimals)}{#if node.unit}<small>{node.unit}</small>{/if}</div>
      {/if}
    </div>
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