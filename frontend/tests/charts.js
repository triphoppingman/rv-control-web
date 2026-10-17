import { createClassComponent } from 'svelte/legacy';
import { tick } from 'svelte';
import { getInstanceByDom } from 'echarts/core';
import Node from '../src/Node.svelte';
import '../src/style.css';

const fixture = document.querySelector('#fixture');
const results = document.querySelector('#results');
const checks = [];
const skipped = [];
let widget;

function assert(condition, message) {
  if (!condition) throw new Error(message);
  checks.push(message);
}

async function render(node, value = 120, ts = 1, theme = 'light') {
  widget?.$destroy();
  widget = createClassComponent({
    component: Node,
    target: fixture,
    props: { node, values: { test: { payload: { value }, ts } }, now: ts * 1000, theme },
  });
  await tick();
}

function chart() {
  return getInstanceByDom(fixture.querySelector('.chart'));
}

async function reading(value, ts) {
  widget.$set({ values: { test: { payload: { value }, ts } }, now: ts * 1000 });
  await tick();
}

try {
  const binding = { topic: 'test', payload_path: 'value' };
  await render({ ...binding, type: 'dial', min: 90, max: 150, show_warning: false });
  let series = chart().getOption().series[0];
  assert(series.type === 'gauge' && series.pointer.show, 'Dial uses a needle gauge');
  assert(series.min === 90 && series.max === 150 && series.data[0].value === 120,
    'Voltage dial preserves its scale and live reading');
  assert(series.startAngle - (120 - series.min) / (series.max - series.min)
    * (series.startAngle - series.endAngle) === 90, '120 V points straight up');
  assert(series.axisLine.lineStyle.color.length === 1, 'Disabled warning has no red arc');
  await reading(123, 2);
  assert(chart().getOption().series[0].data[0].value === 123, 'Dial responds to live updates');
  widget.$set({ theme: 'dark' });
  await tick();
  assert(chart().getOption().series[0].axisLine.lineStyle.color[0][1] === '#43685e',
    'Dial responds to theme changes');

  for (const [min, max, splits] of [
    [0, 4000, 4], [0, 100, 10], [100, 260, 4], [400, 1600, 6],
    [0, 8, 8], [0, 30, 6], [0, 600, 3], [90, 150, 3], [0, 73, 5],
  ]) {
    await render({ ...binding, type: 'dial', min, max });
    assert(chart().getOption().series[0].splitNumber === splits,
      `Dial keeps tick spacing for ${min}-${max}`);
  }
  await render({ ...binding, type: 'dial', min: 0, max: 100, low_warning_below: 15 }, 50);
  assert(chart().getOption().series[0].axisLine.lineStyle.color[0][0] === 0.15,
    'Low-warning arc is preserved');
  await render({ ...binding, type: 'dial' }, null);
  assert(chart().getOption().series[0].data[0].value === 0
    && fixture.textContent.includes('No data'), 'Missing dial reading keeps no-data behavior');

  await render({ ...binding, type: 'gauge', thresholds: [{ at: 0, color: 'blue' }] }, 42);
  series = chart().getOption().series[0];
  assert(series.type === 'gauge' && !series.pointer.show && series.progress.show,
    'Arc gauge keeps progress without a needle');
  assert(series.data[0].value === 42 && series.progress.itemStyle.color === '#3275a4',
    'Arc gauge preserves reading and threshold color');

  await render({ ...binding, type: 'sparkline', history_points: 3, sample_interval_ms: 1000 }, 10, 1);
  assert(chart().getOption().series[0].data.join() === '10', 'Sparkline records initial value');
  await reading(11, 1);
  await reading(12, 1.5);
  assert(chart().getOption().series[0].data.join() === '10',
    'Sparkline ignores duplicate timestamps and too-close readings');
  await reading(20, 2);
  await reading(null, 3);
  await reading(30, 3);
  await reading(40, 4);
  assert(chart().getOption().series[0].data.join() === '20,30,40',
    'Sparkline skips missing values and caps history');
  widget.$set({ theme: 'dark' });
  await tick();
  assert(chart().getOption().series[0].data.length === 3
    && chart().getOption().series[0].areaStyle.opacity === 0.22,
  'Theme updates preserve history without extra samples');
  const previousChart = chart();
  if (document.visibilityState === 'visible') {
    fixture.style.width = '320px';
    for (let attempt = 0; attempt < 20; attempt += 1) {
      if (chart().getWidth() === fixture.querySelector('.chart').clientWidth) break;
      await new Promise((resolve) => setTimeout(resolve, 100));
    }
    assert(chart().getWidth() === fixture.querySelector('.chart').clientWidth,
      'Chart follows container resizing');
  } else {
    skipped.push('Container resizing requires a visible browser tab (ResizeObserver is throttled when hidden)');
  }
  await render({ ...binding, type: 'sparkline', sample_interval_ms: 0 }, 50, 5);
  assert(previousChart.isDisposed(), 'Unmount disposes the ECharts instance');
  assert(chart().getOption().series[0].data.join() === '50', 'Remount clears sparkline history');
  await reading(51, 5.01);
  assert(chart().getOption().series[0].data.join() === '50,51',
    'Zero sample interval accepts every newer timestamp');

  await render({
    type: 'derived', operation: 'difference', label: 'PV-to-battery voltage delta',
    inputs: [
      { topic: 'solar', payload_path: 'pv_voltage' },
      { topic: 'solar', payload_path: 'battery_voltage' },
    ],
  }, null);
  assert(fixture.textContent.includes('No data'), 'Derived widget starts without data');
  widget.$set({
    values: { solar: { payload: { pv_voltage: 13.4, battery_voltage: 13.5 }, ts: 10 } },
    now: 10000,
  });
  await tick();
  assert(fixture.querySelector('.state').textContent === 'Live'
    && fixture.querySelector('.reading').textContent === (-0.1).toLocaleString(undefined, {
      minimumFractionDigits: 0, maximumFractionDigits: 1,
    }), 'Derived widget recalculates when telemetry arrives after mounting');
  widget.$set({ now: 21000 });
  await tick();
  assert(fixture.querySelector('.state').textContent === 'Stale',
    'Derived widget becomes stale as the clock advances');
  widget.$set({ staleAfter: 30000 });
  await tick();
  assert(fixture.querySelector('.state').textContent === 'Live',
    'Derived widget responds to staleness setting changes');
  widget.$set({
    values: { solar: { payload: { pv_voltage: 15, battery_voltage: 13 }, ts: 21 } },
  });
  await tick();
  assert(fixture.querySelector('.reading').textContent === '2',
    'Derived widget recalculates subsequent telemetry');

  const tank = { ...binding, type: 'tank', label: 'Fresh water', min: 0, max: 3, segments: 3 };
  await render(tank, 0);
  assert(fixture.querySelectorAll('.tank-segment').length === 3
    && fixture.querySelectorAll('.tank-segment.filled').length === 0, 'Tank zero is empty');
  for (const level of [1, 2, 3]) {
    await reading(level, level + 1);
    assert(fixture.querySelectorAll('.tank-segment.filled').length === level,
      `Tank level ${level}/3 fills ${level} segments`);
  }
  assert(getComputedStyle(fixture.querySelector('.tank-bar')).flexDirection === 'column-reverse',
    'Tank fills bottom to top');
  const meter = fixture.querySelector('[role="meter"]');
  assert(meter.getAttribute('aria-label') === 'Fresh water'
    && meter.getAttribute('aria-valuenow') === '3', 'Tank exposes an accessible numeric meter');
  await reading(-1, 5);
  assert(fixture.querySelectorAll('.tank-segment.filled').length === 0
    && fixture.querySelector('.reading').textContent === '-1', 'Tank clamps low fill without altering the reading');
  await reading(4, 6);
  assert(fixture.querySelectorAll('.tank-segment.filled').length === 3,
    'Tank clamps high fill to full');
  await reading(null, 7);
  assert(fixture.querySelector('.state').textContent === 'No data'
    && fixture.querySelectorAll('.tank-segment.filled').length === 0
    && !meter.hasAttribute('aria-valuenow'), 'Missing tank data is not represented as a valid empty reading');
  for (const value of ['2', true, NaN, Infinity]) {
    await reading(value, 8);
    assert(fixture.querySelector('.state').textContent === 'Invalid input'
      && fixture.querySelector('.reading').textContent === '--'
      && fixture.querySelectorAll('.tank-segment.filled').length === 0,
    `Tank rejects invalid value ${String(value)}`);
  }
  await render({ ...tank, min: 10, max: 110, segments: 4 }, 60);
  assert(fixture.querySelectorAll('.tank-segment.filled').length === 2,
    'Tank supports four segments and nonzero minimum');
  await render({ ...binding, type: 'tank', thresholds: [{ at: 50, color: 'blue' }] }, 67);
  assert(fixture.querySelectorAll('.tank-segment.filled').length === 2,
    'Default tank range maps percentage readings to thirds');
  assert(getComputedStyle(fixture.querySelector('.tank-segment.filled')).backgroundColor === 'rgb(50, 117, 164)',
    'Tank uses existing threshold colors');
  widget.$set({ now: 12000 });
  await tick();
  assert(fixture.querySelector('.state').textContent === 'Stale', 'Tank reports stale telemetry');
  document.documentElement.setAttribute('data-theme', 'dark');
  assert(getComputedStyle(fixture.querySelector('.tank-segment:not(.filled)')).backgroundColor === 'rgb(28, 46, 40)',
    'Empty tank segments follow the dark theme');
  document.documentElement.removeAttribute('data-theme');

  const tankNames = ['Fresh water', 'Grey water', 'Black water'];
  await render({
    type: 'flow',
    children: tankNames.map((label, index) => ({
      type: 'tank', label, topic: 'test', payload_path: `tanks[${index}]`,
      min: 0, max: 3, segments: 3, min_width: '160px',
    })),
  }, null);
  widget.$set({ values: { test: { payload: { tanks: [3, 1, 2] }, ts: 1 } } });
  await tick();
  const tanks = [...fixture.querySelectorAll('.widget.tank')];
  assert(tanks.length === 3 && tanks.every((element, index) =>
    element.querySelector('.widget-label').textContent === tankNames[index]
    && element.querySelector('[role="meter"]').getAttribute('aria-label') === tankNames[index]),
  'Multiple tanks each display their own visible and accessible label');
  assert(tanks.map((element) => element.querySelectorAll('.tank-segment.filled').length).join() === '3,1,2',
    'Multiple tanks independently bind to their own levels');

  const light = { ...binding, type: 'light', label: 'Living ceiling' };
  await render(light, false);
  assert(fixture.querySelector('.light-reading strong').textContent === 'Off',
    'Boolean light reports Off');
  await reading(true, 2);
  assert(fixture.querySelector('.light-status.on')
    && !fixture.querySelector('.brightness'), 'Boolean light reports On without inventing brightness');
  await reading({ on: true, level: 35 }, 3);
  assert(fixture.querySelector('.brightness').textContent === '35% brightness',
    'Dimmed entity displays its reported percentage');
  await reading({ on: false, level: 80 }, 4);
  assert(fixture.querySelector('.light-reading strong').textContent === 'Off'
    && !fixture.querySelector('.brightness')
    && !fixture.querySelector('.light-status.on'), 'Off overrides remembered brightness');
  for (const level of [0, 100, null]) {
    await reading({ on: true, level }, 5);
    assert(fixture.querySelector('.state').textContent === 'Live',
      `Light accepts boundary or unavailable brightness ${level}`);
  }
  await reading(null, 6);
  assert(fixture.querySelector('.state').textContent === 'No data'
    && fixture.querySelector('.light-reading strong').textContent === '--',
  'Missing light state is not Off');
  for (const value of [1, 'on', {}, [], { on: 1 }, { on: true, level: '35' },
    { on: true, level: -1 }, { on: true, level: 101 }, { on: true, level: NaN }]) {
    await reading(value, 7);
    assert(fixture.querySelector('.state').textContent === 'Invalid input'
      && fixture.querySelector('.light-reading strong').textContent === '--',
    `Light rejects malformed state ${JSON.stringify(value)}`);
  }
  await reading({ on: true, level: 50 }, 8);
  widget.$set({ now: 19000 });
  await tick();
  assert(fixture.querySelector('.state').textContent === 'Stale'
    && fixture.querySelector('.widget.light.stale'), 'Light retains and marks stale status');
  assert(!fixture.querySelector('button, input, [role="button"]'),
    'Light widget contains no controls');

  results.textContent = `PASS: ${checks.length} checks\n${checks.join('\n')}`
    + (skipped.length ? `\nSKIPPED: ${skipped.join('; ')}` : '');
} catch (error) {
  results.textContent = `FAIL: ${error.stack}\nPassed checks:\n${checks.join('\n')}`;
  throw error;
} finally {
  widget?.$destroy();
}
