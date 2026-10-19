<script>
  import { notifications, dismissNotification } from './notifications.js';
</script>

<section class="notifications" aria-label="Notifications">
  {#each [false, true] as isError}
    <div role={isError ? 'alert' : 'status'} aria-atomic="false" class="notification-stack">
      {#each $notifications.filter((item) => (item.kind === 'error') === isError) as item (item.id)}
        <div class="notification" class:success={item.kind === 'success'} class:error-notification={isError}>
          <div class="notification-content">
            {#if item.title}<strong>{item.title}</strong>{/if}
            <p>{item.message}</p>
            {#if item.details.length}
              <details>
                <summary>Entity results ({item.details.length})</summary>
                <ul>{#each item.details as detail}<li>{detail}</li>{/each}</ul>
              </details>
            {/if}
          </div>
          <button type="button" aria-label="Dismiss notification"
            on:click={() => dismissNotification(item.id)}>x</button>
        </div>
      {/each}
    </div>
  {/each}
</section>

<style>
  .notifications { position: fixed; z-index: 100; bottom: max(16px, env(safe-area-inset-bottom)); right: max(16px, env(safe-area-inset-right)); width: min(420px, calc(100% - 32px)); max-height: 45vh; overflow-y: auto; display: grid; gap: 10px; pointer-events: none; }
  .notification-stack { display: grid; gap: 10px; }
  .notification-stack:empty { display: none; }
  .notification { display: flex; align-items: start; gap: 12px; padding: 16px 20px; border: 1px solid var(--border-widget); border-left: 4px solid var(--color-text-muted); border-radius: 24px; background: var(--bg-card); color: var(--color-text); box-shadow: 0 4px 20px #0003; pointer-events: auto; font-size: 13px; }
  .notification.success { border-left-color: var(--border-tab-selected); }
  .error-notification { border-left-color: var(--border-error); background: var(--bg-error); color: var(--color-error); }
  .notification-content { flex: 1; min-width: 0; overflow-wrap: anywhere; }
  strong { display: block; margin-bottom: 4px; }
  p { line-height: 1.5; }
  button { flex: none; cursor: pointer; border: 0; border-radius: 4px; background: transparent; color: inherit; padding: 4px 8px; }
  button:hover { background: var(--border-inner); }
  details { margin-top: 8px; }
  summary { cursor: pointer; }
  ul { padding-left: 18px; margin: 8px 0 0; line-height: 1.5; }
</style>
