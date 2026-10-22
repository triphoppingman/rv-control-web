<script>
  export let record = null;
  export let now = Date.now();
  export let connected = false;
  export let displayTemperatureUnit = 'F';
  export let provider = 'open-meteo';
  export let bindings = {};

  const openMeteoBindings = {
    current_temperature: 'current.temperature_2m',
    apparent_temperature: 'current.apparent_temperature',
    current_weather_code: 'current.weather_code',
    humidity: 'current.relative_humidity_2m',
    wind_speed: 'current.wind_speed_10m',
    wind_direction: 'current.wind_direction_10m',
    wind_gusts: 'current.wind_gusts_10m',
    cloud_cover: 'current.cloud_cover',
    pressure: 'current.pressure_msl',
    precipitation: 'current.precipitation',
    current_time: 'current.time',
    forecast_dates: 'daily.time',
    forecast_weather_codes: 'daily.weather_code',
    forecast_highs: 'daily.temperature_2m_max',
    forecast_lows: 'daily.temperature_2m_min',
    precipitation_probability: 'daily.precipitation_probability_max',
    sunrise: 'daily.sunrise',
    sunset: 'daily.sunset',
    uv_index: 'daily.uv_index_max',
    latitude: 'requested_location.latitude',
    longitude: 'requested_location.longitude',
    timezone: 'timezone',
    fetched_at: 'fetched_at',
  };

  const conditions = {
    0: ['Clear sky', '☀️'],
    1: ['Mostly clear', '🌤️'],
    2: ['Partly cloudy', '⛅'],
    3: ['Overcast', '☁️'],
    45: ['Fog', '🌫️'],
    48: ['Freezing fog', '🌫️'],
    51: ['Light drizzle', '🌦️'],
    53: ['Drizzle', '🌦️'],
    55: ['Dense drizzle', '🌧️'],
    56: ['Freezing drizzle', '🌧️'],
    57: ['Freezing drizzle', '🌧️'],
    61: ['Light rain', '🌦️'],
    63: ['Rain', '🌧️'],
    65: ['Heavy rain', '🌧️'],
    66: ['Freezing rain', '🌧️'],
    67: ['Heavy freezing rain', '🌧️'],
    71: ['Light snow', '🌨️'],
    73: ['Snow', '🌨️'],
    75: ['Heavy snow', '❄️'],
    77: ['Snow grains', '🌨️'],
    80: ['Rain showers', '🌦️'],
    81: ['Rain showers', '🌧️'],
    82: ['Heavy showers', '🌧️'],
    85: ['Snow showers', '🌨️'],
    86: ['Heavy snow showers', '❄️'],
    95: ['Thunderstorm', '⛈️'],
    96: ['Thunderstorm and hail', '⛈️'],
    99: ['Thunderstorm and hail', '⛈️'],
  };

  const compassPoints = ['N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE',
    'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW'];

  function number(value) {
    return typeof value === 'number' && Number.isFinite(value) ? value : null;
  }

  function extract(payload, path) {
    if (!payload || typeof path !== 'string' || !path.trim()) return undefined;
    const parts = path.replace(/^\$\.?/, '').replace(/\[(\d+)\]/g, '.$1').split('.');
    return parts.reduce((current, part) => current?.[part], payload);
  }

  function temperature(value, unit) {
    const celsius = number(value);
    if (celsius === null) return '--';
    return `${Math.round(unit === 'C' ? celsius : celsius * 9 / 5 + 32)}°`;
  }

  function condition(code) {
    return conditions[number(code)] || ['Weather conditions', '🌤️'];
  }

  function compass(degrees) {
    const direction = number(degrees);
    return direction === null ? '--' : compassPoints[Math.round(direction / 22.5) % 16];
  }

  function dayName(date, index) {
    if (index === 0) return 'Today';
    if (index === 1) return 'Tomorrow';
    const parsed = new Date(`${date}T12:00:00Z`);
    return Number.isNaN(parsed.getTime())
      ? date
      : new Intl.DateTimeFormat(undefined, { weekday: 'short', timeZone: 'UTC' }).format(parsed);
  }

  function shortDate(date) {
    const parsed = new Date(`${date}T12:00:00Z`);
    return Number.isNaN(parsed.getTime())
      ? ''
      : new Intl.DateTimeFormat(undefined, { month: 'short', day: 'numeric', timeZone: 'UTC' }).format(parsed);
  }

  function localTime(value) {
    return typeof value === 'string' && value.includes('T') ? value.split('T')[1] : '--';
  }

  function relativeTime(timestamp) {
    if (!Number.isFinite(timestamp)) return 'Update time unavailable';
    const seconds = Math.max(0, Math.floor((now - timestamp) / 1000));
    if (seconds < 60) return 'Updated just now';
    if (seconds < 3600) return `Updated ${Math.floor(seconds / 60)} min ago`;
    if (seconds < 86400) return `Updated ${Math.floor(seconds / 3600)} hr ago`;
    return `Updated ${Math.floor(seconds / 86400)} days ago`;
  }

  $: payload = record?.payload && typeof record.payload === 'object' ? record.payload : null;
  $: unitLabel = String(displayTemperatureUnit).trim().toUpperCase() === 'C' ? 'C' : 'F';
  $: fieldPaths = {
    ...(provider === 'open-meteo' ? openMeteoBindings : {}),
    ...(bindings && typeof bindings === 'object' ? bindings : {}),
  };
  $: field = (name) => extract(payload, fieldPaths[name]);
  $: forecastDates = field('forecast_dates');
  $: forecastCodes = field('forecast_weather_codes');
  $: forecastHighs = field('forecast_highs');
  $: forecastLows = field('forecast_lows');
  $: rainProbabilities = field('precipitation_probability');
  $: sunrise = field('sunrise');
  $: sunset = field('sunset');
  $: uvIndex = field('uv_index');
  $: forecast = Array.isArray(forecastDates)
    ? forecastDates.slice(0, 7).map((date, index) => ({
      date,
      name: dayName(date, index),
      icon: condition(forecastCodes?.[index])[1],
      summary: condition(forecastCodes?.[index])[0],
      high: temperature(forecastHighs?.[index], unitLabel),
      low: temperature(forecastLows?.[index], unitLabel),
      rain: number(rainProbabilities?.[index]),
    }))
    : [];
  $: code = condition(field('current_weather_code'));
  $: fetchedAtValue = field('fetched_at');
  $: fetchedAt = typeof fetchedAtValue === 'string' ? Date.parse(fetchedAtValue) : NaN;
  $: updatedTimestamp = Number.isFinite(fetchedAt) ? fetchedAt : (record?.ts ? record.ts * 1000 : NaN);
  $: latitude = number(field('latitude'));
  $: longitude = number(field('longitude'));
  $: timezone = field('timezone');
  $: location = latitude !== null && longitude !== null
    ? `${latitude.toFixed(2)}°, ${longitude.toFixed(2)}°`
    : timezone || 'Location unavailable';
  $: currentTemperature = field('current_temperature');
  $: apparentTemperature = field('apparent_temperature');
  $: currentHumidity = field('humidity');
  $: windSpeed = number(field('wind_speed'));
  $: windDirection = field('wind_direction');
  $: windGusts = number(field('wind_gusts'));
  $: cloudCover = field('cloud_cover');
  $: pressure = number(field('pressure'));
  $: precipitation = number(field('precipitation'));
  $: currentTime = field('current_time');
</script>

<section class="weather-view" aria-label="Weather forecast">
  {#if !payload}
    <div class="weather-empty">
      <span class="empty-icon" aria-hidden="true">☁️</span>
      <h2>{connected ? 'Waiting for weather data' : 'Weather data unavailable'}</h2>
      <p>Live conditions will appear here when a publication arrives on <code>rv/weather</code>.</p>
    </div>
  {:else}
    <section class="current-card" aria-label="Current weather">
      <div class="current-copy">
        <div class="location">{location}</div>
        <div class="condition">{code[0]}</div>
        <div class="current-reading" aria-label={`Temperature ${temperature(currentTemperature, unitLabel)} ${unitLabel === 'F' ? 'Fahrenheit' : 'Celsius'}`}>
          {temperature(currentTemperature, unitLabel)}<span>{unitLabel}</span>
        </div>
        <div class="feels-like">
          Feels like {temperature(apparentTemperature, unitLabel)}{unitLabel}
          {#if forecast[0]}<span> · H {forecast[0].high} / L {forecast[0].low}</span>{/if}
        </div>
      </div>
      <div class="current-icon" aria-hidden="true">{code[1]}</div>
      <div class="current-footer">
        <span>{timezone || 'Local time'}{#if currentTime} · {localTime(currentTime)}{/if}</span>
        <span>{relativeTime(updatedTimestamp)}</span>
      </div>
    </section>

    <section class="conditions-grid" aria-label="Current conditions">
      <article class="metric-card">
        <span class="metric-icon" aria-hidden="true">💧</span>
        <div><span class="metric-label">Humidity</span><strong>{number(currentHumidity) ?? '--'}<small>%</small></strong></div>
      </article>
      <article class="metric-card">
        <span class="metric-icon" aria-hidden="true">🌬️</span>
        <div><span class="metric-label">Wind</span><strong>{windSpeed === null ? '--' : Math.round(windSpeed * 0.621371)}<small> mph {compass(windDirection)}</small></strong></div>
      </article>
      <article class="metric-card">
        <span class="metric-icon" aria-hidden="true">💨</span>
        <div><span class="metric-label">Wind gusts</span><strong>{windGusts === null ? '--' : Math.round(windGusts * 0.621371)}<small> mph</small></strong></div>
      </article>
      <article class="metric-card">
        <span class="metric-icon" aria-hidden="true">☁️</span>
        <div><span class="metric-label">Cloud cover</span><strong>{number(cloudCover) ?? '--'}<small>%</small></strong></div>
      </article>
      <article class="metric-card">
        <span class="metric-icon" aria-hidden="true">◉</span>
        <div><span class="metric-label">Pressure</span><strong>{pressure === null ? '--' : (pressure * 0.029529983).toFixed(2)}<small> inHg</small></strong></div>
      </article>
      <article class="metric-card">
        <span class="metric-icon" aria-hidden="true">☔</span>
        <div><span class="metric-label">Precipitation</span><strong>{precipitation === null ? '--' : (precipitation / 25.4).toFixed(2)}<small> in</small></strong></div>
      </article>
    </section>

    <section class="forecast-card" aria-label="7-day forecast">
      <div class="section-heading">
        <div><span class="eyebrow">LOOK AHEAD</span><h2>7-day forecast</h2></div>
        <span class="unit-note">Temperatures in °{unitLabel}</span>
      </div>
      {#if forecast.length}
        <div class="forecast-list">
          {#each forecast as day, index (day.date)}
            <article class="forecast-day" class:today={index === 0}>
              <div class="forecast-date"><strong>{day.name}</strong><span>{shortDate(day.date)}</span></div>
              <span class="forecast-icon" aria-label={day.summary}>{day.icon}</span>
              <div class="forecast-range"><strong>{day.high}</strong><span>{day.low}</span></div>
              <div class="rain-chance" aria-label={`Precipitation chance ${day.rain ?? 'unavailable'}`}>
                <span aria-hidden="true">💧</span> {day.rain === null ? '--' : `${day.rain}%`}
              </div>
            </article>
          {/each}
        </div>
      {:else}
        <p class="forecast-empty">Forecast data is not available yet.</p>
      {/if}
    </section>

    <section class="sun-card" aria-label="Daylight and UV">
      <div class="sun-item"><span aria-hidden="true">🌅</span><div><span class="metric-label">Sunrise</span><strong>{localTime(Array.isArray(sunrise) ? sunrise[0] : sunrise)}</strong></div></div>
      <div class="sun-track" aria-hidden="true"><span>☀</span><div></div><span>☾</span></div>
      <div class="sun-item"><span aria-hidden="true">🌇</span><div><span class="metric-label">Sunset</span><strong>{localTime(Array.isArray(sunset) ? sunset[0] : sunset)}</strong></div></div>
      <div class="uv-index"><span class="metric-label">Today's max UV</span><strong>{number(Array.isArray(uvIndex) ? uvIndex[0] : uvIndex) ?? '--'}</strong></div>
    </section>
  {/if}
</section>

<style>
  .weather-view { display: grid; gap: 18px; }
  .current-card {
    position: relative; display: grid; grid-template-columns: 1fr auto; gap: 12px;
    overflow: hidden; min-height: 225px; padding: clamp(22px, 4vw, 38px);
    color: #f5fbf8; background:
      radial-gradient(circle at 85% 10%, #ffffff23, transparent 32%),
      linear-gradient(120deg, #174c43, #207c70 58%, #42a58e);
    border: 1px solid #277365; border-radius: 7px; box-shadow: 0 7px 24px #173f3724;
  }
  .current-copy { position: relative; z-index: 1; }
  .location { color: #d1e9df; font-size: 13px; font-weight: 600; letter-spacing: .02em; }
  .condition { margin-top: 9px; font-size: 16px; font-weight: 500; }
  .current-reading { margin-top: 3px; font: 600 clamp(64px, 10vw, 96px)/1 'Space Grotesk', sans-serif; letter-spacing: -.07em; }
  .current-reading span { margin-left: 7px; font: 500 21px 'DM Sans', sans-serif; letter-spacing: 0; vertical-align: top; }
  .feels-like { margin-top: 9px; color: #d1e9df; font-size: 13px; }
  .current-icon { align-self: center; padding: 0 clamp(8px, 3vw, 34px); font-size: clamp(64px, 10vw, 104px); filter: drop-shadow(0 7px 8px #153b3340); }
  .current-footer { grid-column: 1 / -1; display: flex; justify-content: space-between; gap: 12px; padding-top: 15px; border-top: 1px solid #ffffff30; color: #c5e1d7; font-size: 11px; }
  .conditions-grid { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 12px; }
  .metric-card { display: flex; align-items: center; gap: 13px; min-width: 0; padding: 17px; background: var(--bg-card); border: 1px solid var(--border-card); border-radius: 5px; box-shadow: var(--card-shadow); }
  .metric-icon { display: grid; place-items: center; width: 38px; height: 38px; flex: 0 0 38px; background: var(--border-inner); border-radius: 50%; font-size: 17px; }
  .metric-card > div, .sun-item > div { display: flex; flex-direction: column; gap: 3px; min-width: 0; }
  .metric-label { color: var(--color-text-muted); font-size: 11px; font-weight: 600; }
  .metric-card strong, .sun-item strong { color: var(--color-reading); font: 600 19px 'Space Grotesk', sans-serif; white-space: nowrap; }
  .metric-card strong small { color: var(--color-text-muted); font: 500 11px 'DM Sans', sans-serif; }
  .forecast-card { padding: 22px; background: var(--bg-card); border: 1px solid var(--border-card); border-top: 3px solid var(--border-card-top); border-radius: 5px; box-shadow: var(--card-shadow); }
  .section-heading { display: flex; align-items: end; justify-content: space-between; gap: 12px; margin-bottom: 15px; }
  .eyebrow { color: var(--color-eyebrow); font-size: 10px; font-weight: 700; letter-spacing: .08em; }
  h2 { margin: 4px 0 0; color: var(--color-heading); font: 600 19px 'Space Grotesk', sans-serif; }
  .unit-note { color: var(--color-text-muted); font-size: 11px; }
  .forecast-list { display: grid; grid-template-columns: repeat(7, minmax(0, 1fr)); }
  .forecast-day { display: flex; flex-direction: column; align-items: center; gap: 11px; min-width: 0; padding: 13px 6px 8px; border-right: 1px solid var(--border-inner); }
  .forecast-day:last-child { border-right: 0; }
  .forecast-day.today { background: color-mix(in srgb, var(--border-card-top) 9%, transparent); border-radius: 4px; }
  .forecast-date { display: flex; flex-direction: column; align-items: center; gap: 2px; }
  .forecast-date strong { color: var(--color-heading); font-size: 12px; }
  .forecast-date span { color: var(--color-text-muted); font-size: 10px; }
  .forecast-icon { min-height: 31px; font-size: 25px; }
  .forecast-range { display: flex; gap: 9px; color: var(--color-text-muted); font-size: 12px; }
  .forecast-range strong { color: var(--color-reading); }
  .rain-chance { color: var(--color-text-muted); font-size: 10px; white-space: nowrap; }
  .rain-chance span { color: #529dc4; }
  .sun-card { display: grid; grid-template-columns: auto minmax(80px, 1fr) auto auto; align-items: center; gap: clamp(12px, 3vw, 30px); padding: 17px 21px; background: var(--bg-card); border: 1px solid var(--border-card); border-radius: 5px; }
  .sun-item { display: flex; align-items: center; gap: 10px; }
  .sun-item > span { font-size: 22px; }
  .sun-item strong { font-size: 15px; }
  .sun-track { display: flex; align-items: center; gap: 8px; color: #d59a42; font-size: 15px; }
  .sun-track div { height: 2px; flex: 1; background: linear-gradient(90deg, #e6b65d, #e8ddd0, #697f91); border-radius: 2px; }
  .uv-index { display: flex; flex-direction: column; gap: 3px; padding-left: clamp(12px, 2vw, 24px); border-left: 1px solid var(--border-inner); }
  .uv-index strong { color: var(--color-reading); font: 600 19px 'Space Grotesk', sans-serif; }
  .weather-empty { display: grid; justify-items: center; gap: 12px; padding: 70px 20px; text-align: center; background: var(--bg-card); border: 1px solid var(--border-card); border-radius: 5px; }
  .empty-icon { font-size: 42px; }
  .weather-empty h2 { margin: 0; }
  .weather-empty p, .forecast-empty { color: var(--color-text-muted); font-size: 13px; }
  .weather-empty code { color: var(--color-reading); }
  .forecast-empty { padding: 8px 0; }
  @media (max-width: 800px) {
    .conditions-grid { grid-template-columns: repeat(2, minmax(0, 1fr)); }
    .forecast-list { grid-template-columns: repeat(4, minmax(0, 1fr)); row-gap: 8px; }
    .forecast-day:nth-child(4) { border-right: 0; }
  }
  @media (max-width: 520px) {
    .current-card { min-height: 195px; }
    .current-icon { padding: 0 2px; }
    .conditions-grid { gap: 8px; }
    .metric-card { gap: 9px; padding: 12px 10px; }
    .metric-icon { width: 31px; height: 31px; flex-basis: 31px; font-size: 14px; }
    .metric-card strong { font-size: 16px; }
    .forecast-card { padding: 17px 10px; }
    .forecast-day { padding-inline: 3px; }
    .forecast-list { grid-template-columns: repeat(4, minmax(0, 1fr)); }
    .sun-card { grid-template-columns: 1fr 1fr; }
    .sun-track { grid-column: 1 / -1; grid-row: 2; }
    .uv-index { justify-self: end; }
  }
</style>
