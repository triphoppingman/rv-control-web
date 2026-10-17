<script>
  export let value = null;

  $: on = typeof value === 'boolean' ? value : value?.on;
  $: level = typeof value === 'object' && value !== null ? value.level : null;
  $: valid = typeof on === 'boolean'
    && (level == null || (typeof level === 'number' && Number.isFinite(level) && level >= 0 && level <= 100));
  $: brightness = valid && on ? (level ?? 100) : 0;
</script>

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

<style>
  .light-status { display: flex; align-items: center; gap: 16px; margin-top: 18px; color: var(--color-text-muted); }
  .light-status.on { color: var(--accent, #147d73); }
  .bulb { width: 48px; height: 56px; flex: none; fill: none; stroke: currentColor; stroke-width: 2.5; stroke-linecap: round; stroke-linejoin: round; }
  .bulb-fill { fill: currentColor; stroke: none; }
  .light-reading { display: flex; flex-direction: column; gap: 4px; }
  strong { font: 600 26px 'Space Grotesk', sans-serif; }
  .brightness { font-size: 12px; color: var(--color-text-muted); }
  :global(.stale) .light-status { opacity: 0.55; }
</style>
