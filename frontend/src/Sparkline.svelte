<script>
  import * as echarts from 'echarts/core';
  import { LineChart } from 'echarts/charts';
  import { GridComponent } from 'echarts/components';
  import Chart from './Chart.svelte';

  echarts.use([LineChart, GridComponent]);

  export let value = null;
  export let min = 0;
  export let max = 100;
  export let color = '#147d73';
  export let theme = 'light';
  export let historyPoints = 60;
  export let sampleIntervalMs = 1000;
  export let timestamp = null;

  let history = [];

  // History belongs to this widget and is discarded when it unmounts.
  $: if (Number.isFinite(value) && Number.isFinite(timestamp)) {
    const last = history[history.length - 1];
    if (!last || (timestamp > last.ts && timestamp - last.ts >= sampleIntervalMs)) {
      history = [...history.slice(-(historyPoints - 1)), { ts: timestamp, value }];
    }
  }

  $: options = {
    animation: false,
    grid: { left: 2, right: 2, top: 5, bottom: 5 },
    xAxis: { type: 'category', show: false, data: history.map((_, index) => index) },
    yAxis: { type: 'value', show: false, min, max },
    series: [{
      type: 'line',
      data: history.map((point) => point.value),
      symbol: 'none',
      smooth: true,
      lineStyle: { color, width: 2 },
      areaStyle: { color, opacity: theme === 'dark' ? 0.22 : 0.12 },
    }],
  };
</script>

<Chart {options} line />
