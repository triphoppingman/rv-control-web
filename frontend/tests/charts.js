import { createClassComponent } from 'svelte/legacy';
import { tick } from 'svelte';
import { getInstanceByDom } from 'echarts/core';
import Node from '../src/Node.svelte';
import '../src/style.css';

const fixture = document.querySelector('#fixture');
const results = document.querySelector('#results');
const checks = [];
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
  fixture.style.width = '320px';
  await new Promise((resolve) => setTimeout(resolve, 100));
  assert(chart().getWidth() === fixture.querySelector('.chart').clientWidth,
    'Chart follows container resizing');
  await render({ ...binding, type: 'sparkline', sample_interval_ms: 0 }, 50, 5);
  assert(previousChart.isDisposed(), 'Unmount disposes the ECharts instance');
  assert(chart().getOption().series[0].data.join() === '50', 'Remount clears sparkline history');
  await reading(51, 5.01);
  assert(chart().getOption().series[0].data.join() === '50,51',
    'Zero sample interval accepts every newer timestamp');

  results.textContent = `PASS: ${checks.length} checks\n${checks.join('\n')}`;
} catch (error) {
  results.textContent = `FAIL: ${error.stack}\nPassed checks:\n${checks.join('\n')}`;
  throw error;
} finally {
  widget?.$destroy();
}
