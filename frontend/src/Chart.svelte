<script>
  import { onMount } from 'svelte';
  import * as echarts from 'echarts/core';
  import { GaugeChart, LineChart } from 'echarts/charts';
  import { GridComponent } from 'echarts/components';
  import { CanvasRenderer } from 'echarts/renderers';

  echarts.use([GaugeChart, LineChart, GridComponent, CanvasRenderer]);

  export let type = 'gauge';
  export let value = null;
  export let min = 0;
  export let max = 100;
  export let color = '#147d73';

  let element;
  let chart;
  let history = [];

  // Sparkline points live only for this mounted widget; tab changes discard them.
  $: if (chart) {
    if (type === 'sparkline' && typeof value === 'number') {
      history = [...history.slice(-59), value];
    }
    chart.setOption(type === 'sparkline' ? {
      animation: false,
      grid: { left: 2, right: 2, top: 5, bottom: 5 },
      xAxis: { type: 'category', show: false, data: history.map((_, index) => index) },
      yAxis: { type: 'value', show: false, min, max },
      series: [{ type: 'line', data: history, symbol: 'none', smooth: true,
        lineStyle: { color, width: 2 }, areaStyle: { color, opacity: 0.12 } }],
    } : {
      series: [{ type: 'gauge', min, max, startAngle: type === 'dial' ? 210 : 180,
        endAngle: type === 'dial' ? -30 : 0, radius: '95%', center: ['50%', type === 'dial' ? '52%' : '68%'],
        progress: { show: true, width: 12, itemStyle: { color } },
        axisLine: { lineStyle: { width: 12, color: [[1, '#dce5e1']] } },
        axisTick: { show: false }, splitLine: { show: false }, axisLabel: { show: false },
        pointer: { show: type === 'dial', width: 3, length: '58%', itemStyle: { color: '#163832' } },
        anchor: { show: type === 'dial', size: 8 }, detail: { show: false },
        data: [{ value: typeof value === 'number' ? value : min }],
      }],
    }, true);
  }

  onMount(() => {
    chart = echarts.init(element);
    // Canvas sizing follows the widget container, not the browser window.
    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(element);
    return () => { observer.disconnect(); chart.dispose(); chart = null; };
  });
</script>

<div bind:this={element} class:line={type === 'sparkline'} class="chart" aria-hidden="true"></div>