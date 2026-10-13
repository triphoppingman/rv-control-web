<script>
  import { onMount } from 'svelte';

  export let node;
  export let values;
  export let now;
  export let staleAfter = 10000;

  // Extract path from payload with dot/bracket support
  function extract(payload, path) {
    if (!payload || !path) return undefined;
    const parts = path.replace(/^\$\.?/, '').replace(/\[(\d+)\]/g, '.$1').split('.');
    return parts.reduce((current, part) => current?.[part], payload);
  }

  // Heading angles to 16-point cardinal compass direction
  function toCompass(degrees) {
    if (typeof degrees !== 'number' || !Number.isFinite(degrees)) return '';
    const points = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE', 'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW'];
    const index = Math.round(((degrees % 360 + 360) % 360) / 22.5) % 16;
    return points[index];
  }

  $: record = values[node.topic];
  $: payload = record?.payload;

  $: lat = extract(payload, node.lat_path || 'lat');
  $: lon = extract(payload, node.lon_path || 'lon');
  $: track = extract(payload, node.track_path || 'track');
  $: alt = extract(payload, node.alt_path || 'alt');
  $: speed = extract(payload, node.speed_path || 'speed');
  $: mode = extract(payload, node.mode_path || 'mode');

  $: hasCoords = typeof lat === 'number' && Number.isFinite(lat) && typeof lon === 'number' && Number.isFinite(lon);
  $: hasTrack = typeof track === 'number' && Number.isFinite(track);
  $: hasAlt = typeof alt === 'number' && Number.isFinite(alt);
  $: hasSpeed = typeof speed === 'number' && Number.isFinite(speed);

  $: isStale = !record || (now - record.ts * 1000 > (node.stale_after_ms ?? staleAfter));
  $: statusText = !record ? 'No data' : isStale ? 'Stale' : (mode === 1 ? 'No fix' : mode === 2 ? '2D Fix' : mode === 3 ? '3D Fix' : 'Live');

  // Unit conversions
  $: altitudeUnit = node.altitude_unit || 'ft';
  $: displayedAltitude = hasAlt
    ? (altitudeUnit === 'ft' ? Math.round(alt * 3.28084) : Math.round(alt))
    : null;

  $: speedUnit = node.speed_unit || 'mph';
  $: displayedSpeed = hasSpeed
    ? (speedUnit === 'mph' ? (speed * 2.23694).toFixed(0) : speedUnit === 'km/h' ? (speed * 3.6).toFixed(0) : (speed * 1.94384).toFixed(0))
    : null;

  // Track & heading rotation
  $: headingAngle = hasTrack ? track : 0;
  $: orientation = node.orientation || 'north_up';

  let currentZoom = node.zoom ?? 14;
  let zoomControl = node.zoom_control !== false;
  let showHeading = node.show_heading !== false;
  let showAltitude = node.show_altitude !== false;
  let showSpeed = node.show_speed !== false;

  // Zoom controls
  function zoomIn() {
    if (currentZoom < 19) currentZoom += 1;
  }
  function zoomOut() {
    if (currentZoom > 2) currentZoom -= 1;
  }

  // Web Mercator slippy tile projection formulas
  function lon2tile(lonDeg, zoom) {
    return ((lonDeg + 180) / 360) * Math.pow(2, zoom);
  }

  function lat2tile(latDeg, zoom) {
    const latRad = (latDeg * Math.PI) / 180;
    return ((1 - Math.log(Math.tan(latRad) + 1 / Math.cos(latRad)) / Math.PI) / 2) * Math.pow(2, zoom);
  }

  const TILE_SIZE = 256;
  let containerWidth = 400;
  let containerHeight = 300;
  let containerElement;

  $: tileXFloat = hasCoords ? lon2tile(lon, currentZoom) : lon2tile(0, currentZoom);
  $: tileYFloat = hasCoords ? lat2tile(lat, currentZoom) : lat2tile(0, currentZoom);

  // Compute bounding tile coordinates required to fill the viewport
  $: tiles = (() => {
    if (!containerWidth || !containerHeight) return [];
    const halfW = containerWidth / 2;
    const halfH = containerHeight / 2;
    // Account for rotation diagonal if heading_up
    const radius = orientation === 'heading_up' ? Math.hypot(halfW, halfH) : Math.max(halfW, halfH);
    const minTileX = Math.floor((tileXFloat * TILE_SIZE - radius) / TILE_SIZE);
    const maxTileX = Math.floor((tileXFloat * TILE_SIZE + radius) / TILE_SIZE);
    const minTileY = Math.floor((tileYFloat * TILE_SIZE - radius) / TILE_SIZE);
    const maxTileY = Math.floor((tileYFloat * TILE_SIZE + radius) / TILE_SIZE);

    const maxTilesOnZoom = Math.pow(2, currentZoom);
    const result = [];
    const template = node.tile_url || 'https://tile.openstreetmap.org/{z}/{x}/{y}.png';

    for (let ty = Math.max(0, minTileY); ty <= Math.min(maxTilesOnZoom - 1, maxTileY); ty++) {
      for (let tx = minTileX; tx <= maxTileX; tx++) {
        const wrappedX = ((tx % maxTilesOnZoom) + maxTilesOnZoom) % maxTilesOnZoom;
        const url = template
          .replace('{z}', currentZoom)
          .replace('{x}', wrappedX)
          .replace('{y}', ty);
        const left = Math.round(tx * TILE_SIZE - tileXFloat * TILE_SIZE + halfW);
        const top = Math.round(ty * TILE_SIZE - tileYFloat * TILE_SIZE + halfH);
        result.push({ key: `${currentZoom}_${tx}_${ty}`, url, left, top });
      }
    }
    return result;
  })();

  onMount(() => {
    if (!containerElement) return;
    const observer = new ResizeObserver((entries) => {
      for (const entry of entries) {
        containerWidth = entry.contentRect.width || 400;
        containerHeight = entry.contentRect.height || 300;
      }
    });
    observer.observe(containerElement);
    return () => observer.disconnect();
  });
</script>

<div
  class="widget map-widget"
  class:stale={isStale}
  style="--span:{node.span || 12}; --min-width:{node.min_width || 'auto'};"
>
  <div class="widget-top">
    <span class="widget-label">{node.label || 'Map'}</span>
    <span class="state" class:offline={!record || isStale || mode === 1}>{statusText}</span>
  </div>

  <div
    bind:this={containerElement}
    class="map-viewport"
    style="height: {node.height || '360px'};"
    tabindex="0"
    role="region"
    aria-label="Current location map"
  >
    {#if hasCoords}
      <!-- Tiles canvas / layer -->
      <div
        class="map-tiles-layer"
        style="transform: {orientation === 'heading_up' ? `rotate(${-headingAngle}deg)` : 'none'}; transform-origin: 50% 50%;"
      >
        {#each tiles as tile (tile.key)}
          <img
            src={tile.url}
            alt=""
            loading="lazy"
            class="map-tile"
            style="left: {tile.left}px; top: {tile.top}px;"
          />
        {/each}
      </div>

      <!-- Center Vehicle Marker -->
      <div class="map-marker-container">
        <div
          class="vehicle-marker"
          style="transform: rotate({orientation === 'north_up' ? headingAngle : 0}deg);"
          title="Vehicle Location"
        >
          <svg viewBox="0 0 32 32" width="34" height="34" class="marker-icon">
            <defs>
              <filter id="marker-shadow" x="-30%" y="-30%" width="160%" height="160%">
                <feDropShadow dx="0" dy="2" stdDeviation="2.5" flood-color="#000" flood-opacity="0.35" />
              </filter>
            </defs>
            <circle cx="16" cy="16" r="14" fill="#147d73" stroke="#ffffff" stroke-width="2.5" filter="url(#marker-shadow)" />
            <polygon points="16,6 23,23 16,19 9,23" fill="#ffffff" />
          </svg>
        </div>
      </div>
    {:else}
      <div class="map-no-coords">
        <p>Awaiting GPS coordinates...</p>
      </div>
    {/if}

    <!-- Optional Zoom Controls -->
    {#if zoomControl}
      <div class="map-controls">
        <button type="button" class="zoom-btn" on:click={zoomIn} aria-label="Zoom in">+</button>
        <button type="button" class="zoom-btn" on:click={zoomOut} aria-label="Zoom out">−</button>
      </div>
    {/if}

    <!-- Telemetry HUD Overlay (Heading, Altitude, Speed) -->
    <div class="map-hud-overlay">
      {#if showHeading && hasTrack}
        <div class="hud-pill">
          <span class="hud-label">HDG</span>
          <strong>{Math.round(track)}° {toCompass(track)}</strong>
        </div>
      {/if}
      {#if showAltitude && displayedAltitude !== null}
        <div class="hud-pill">
          <span class="hud-label">ALT</span>
          <strong>{displayedAltitude.toLocaleString()} <small>{altitudeUnit}</small></strong>
        </div>
      {/if}
      {#if showSpeed && displayedSpeed !== null}
        <div class="hud-pill">
          <span class="hud-label">SPD</span>
          <strong>{displayedSpeed} <small>{speedUnit}</small></strong>
        </div>
      {/if}
      {#if hasCoords}
        <div class="hud-pill coords-pill">
          <span>{Math.abs(lat).toFixed(4)}° {lat >= 0 ? 'N' : 'S'}, {Math.abs(lon).toFixed(4)}° {lon >= 0 ? 'E' : 'W'}</span>
        </div>
      {/if}
    </div>
  </div>
</div>

<style>
  .map-widget {
    padding: 19px;
    display: flex;
    flex-direction: column;
    gap: 12px;
  }
  .map-viewport {
    position: relative;
    width: 100%;
    overflow: hidden;
    background-color: #d8e5e0;
    border-radius: 4px;
    border: 1px solid #c8d7d1;
    user-select: none;
  }
  .map-tiles-layer {
    position: absolute;
    width: 100%;
    height: 100%;
    pointer-events: none;
    transition: transform 0.2s linear;
  }
  .map-tile {
    position: absolute;
    width: 256px;
    height: 256px;
    user-select: none;
    pointer-events: none;
  }
  .map-marker-container {
    position: absolute;
    top: 50%;
    left: 50%;
    transform: translate(-50%, -50%);
    pointer-events: none;
    z-index: 10;
  }
  .vehicle-marker {
    display: flex;
    align-items: center;
    justify-content: center;
    transition: transform 0.3s ease-out;
  }
  .marker-icon {
    display: block;
  }
  .map-no-coords {
    display: grid;
    place-items: center;
    height: 100%;
    color: #688077;
    font-size: 14px;
  }
  .map-controls {
    position: absolute;
    top: 10px;
    right: 10px;
    display: flex;
    flex-direction: column;
    gap: 4px;
    z-index: 20;
  }
  .zoom-btn {
    width: 32px;
    height: 32px;
    background: #ffffffdd;
    border: 1px solid #a4c1b7;
    border-radius: 4px;
    color: #18312d;
    font-size: 18px;
    font-weight: 700;
    line-height: 1;
    display: grid;
    place-items: center;
    cursor: pointer;
    box-shadow: 0 2px 6px #00000022;
  }
  .zoom-btn:hover {
    background: #ffffff;
    color: #147d73;
  }
  .map-hud-overlay {
    position: absolute;
    bottom: 10px;
    left: 10px;
    right: 10px;
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
    z-index: 20;
    pointer-events: none;
  }
  .hud-pill {
    background: #18312dee;
    color: #ffffff;
    padding: 5px 10px;
    border-radius: 4px;
    font-size: 12px;
    display: flex;
    align-items: center;
    gap: 6px;
    box-shadow: 0 2px 8px #00000033;
    backdrop-filter: blur(4px);
  }
  .hud-label {
    font-size: 10px;
    color: #90c2b2;
    font-weight: 700;
    letter-spacing: 0.5px;
  }
  .hud-pill strong {
    font-family: 'Space Grotesk', sans-serif;
    font-weight: 600;
  }
  .hud-pill small {
    font-size: 10px;
    font-weight: normal;
    color: #b7cfc8;
    margin-left: 2px;
  }
  .coords-pill {
    margin-left: auto;
    font-family: 'Space Grotesk', sans-serif;
    font-size: 11px;
    color: #cfe5de;
    background: #18312dcc;
  }
  @media (max-width: 600px) {
    .coords-pill {
      margin-left: 0;
      width: 100%;
    }
  }
</style>