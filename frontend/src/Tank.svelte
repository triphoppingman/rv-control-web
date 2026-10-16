<script>
  export let value = null;
  export let min = 0;
  export let max = 100;
  export let segments = 3;
  export let label = 'Tank level';

  $: valid = typeof value === 'number' && Number.isFinite(value);
  $: filled = valid ? Math.round(Math.max(0, Math.min(1, (value - min) / (max - min))) * segments) : 0;
</script>

<div class="tank-level">
  <div class="tank-bar" role="meter" aria-label={label} aria-valuemin={min} aria-valuemax={max}
    aria-valuenow={valid ? Math.max(min, Math.min(max, value)) : undefined}
    aria-valuetext={valid ? String(value) : 'No data'}>
    {#each Array(segments) as _, index}
      <div class="tank-segment" class:filled={valid && index < filled}></div>
    {/each}
  </div>
  <div class="tank-scale" aria-hidden="true"><span>Full</span><span>Empty</span></div>
</div>

<style>
  .tank-level { display: flex; justify-content: center; gap: 10px; margin-top: 14px; }
  .tank-bar {
    display: flex;
    flex-direction: column-reverse;
    gap: 4px;
    width: 76px;
    height: 160px;
    padding: 5px;
    border: 2px solid var(--border-card-top);
    border-radius: 9px;
  }
  .tank-segment { flex: 1; background: var(--border-inner); border-radius: 3px; }
  .tank-segment.filled { background: var(--accent, #147d73); }
  .tank-scale { display: flex; flex-direction: column; justify-content: space-between; color: var(--color-text-muted); font-size: 12px; padding: 5px 0; }
</style>
