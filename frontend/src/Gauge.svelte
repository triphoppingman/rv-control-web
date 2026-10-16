<script>
  import * as echarts from 'echarts/core';
  import { GaugeChart } from 'echarts/charts';
  import Chart from './Chart.svelte';

  echarts.use([GaugeChart]);

  export let value = null;
  export let min = 0;
  export let max = 100;
  export let color = '#147d73';
  export let theme = 'light';

  $: isDark = theme === 'dark';
  $: options = {
    series: [{
      type: 'gauge',
      min,
      max,
      startAngle: 200,
      endAngle: -20,
      radius: '86%',
      center: ['50%', '72%'],
      progress: { show: true, width: 8, itemStyle: { color } },
      axisLine: { lineStyle: { width: 8, color: [[1, isDark ? '#233730' : '#dce5e1']] } },
      splitLine: {
        show: true,
        distance: -15,
        length: 7,
        lineStyle: { color: isDark ? '#6b9184' : '#3d5c52', width: 2 },
      },
      axisTick: {
        show: true,
        splitNumber: 4,
        distance: -14,
        length: 4,
        lineStyle: { color: isDark ? '#4a6f62' : '#889e96', width: 1 },
      },
      axisLabel: {
        show: true,
        distance: -18,
        color: isDark ? '#80a89a' : '#5b766c',
        fontSize: 10,
        fontWeight: 600,
        fontFamily: "'Space Grotesk', sans-serif",
        formatter: (v) => Math.round(v),
      },
      pointer: { show: false },
      anchor: { show: false },
      detail: { show: false },
      data: [{ value: typeof value === 'number' ? value : min }],
    }],
  };
</script>

<Chart {options} />
