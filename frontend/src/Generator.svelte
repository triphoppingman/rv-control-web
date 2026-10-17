<script>
  export let value = null;

  $: status = value?.status;
  $: statusText = status == null ? 'No data' : status === 'running' ? 'Running'
    : status === 'stopped' ? 'Stopped' : `Unknown (${status})`;
</script>

<div class="generator-status" class:running={status === 'running'}>
  <svg viewBox="0 0 56 48" aria-hidden="true">
    <rect x="6" y="12" width="44" height="28" rx="4" />
    <path d="M18 12V6h20v6M12 40v4M44 40v4M36 20h8M36 26h8M36 32h8M24 18l-8 10h8l-4 8 12-12h-9Z" />
  </svg>
  <strong>{statusText}</strong>
</div>
<dl>
  <div><dt>Engine run hours</dt><dd>{value?.run_hours == null ? '--' : value.run_hours.toLocaleString(undefined, { minimumFractionDigits: 1, maximumFractionDigits: 1 })}<small> h</small></dd></div>
  <div><dt>Start relay</dt><dd>{value?.starting == null ? 'No data' : value.starting ? 'Active' : 'Inactive'}</dd></div>
  <div><dt>Stop relay</dt><dd>{value?.stopping == null ? 'No data' : value.stopping ? 'Active' : 'Inactive'}</dd></div>
</dl>

<style>
  .generator-status { display: flex; align-items: center; gap: 16px; margin-top: 18px; color: var(--color-text-muted); }
  .generator-status.running { color: var(--accent, #147d73); }
  svg { width: 56px; height: 48px; flex: none; fill: none; stroke: currentColor; stroke-width: 2; stroke-linecap: round; stroke-linejoin: round; }
  strong { font: 600 26px 'Space Grotesk', sans-serif; overflow-wrap: anywhere; }
  dl { margin: 18px 0 0; display: grid; gap: 10px; }
  dl > div { display: flex; justify-content: space-between; gap: 16px; }
  dt, small { color: var(--color-text-muted); font-size: 12px; }
  dd { margin: 0; color: var(--color-reading); }
  :global(.widget.stale) .generator-status, :global(.widget.stale) dl { opacity: 0.55; }
</style>
