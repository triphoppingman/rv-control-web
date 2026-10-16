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
  export let theme = 'light';
  export let historyPoints = 60;
  export let sampleIntervalMs = 1000;
  export let timestamp = null;
  export let lowWarningBelow = null;

  let element;
  let chart;
  let history = [];

  // Sparkline points live only for this mounted widget; tab changes discard them.
  $: if (chart) {
    if (type === 'sparkline' && Number.isFinite(value) && Number.isFinite(timestamp)) {
      const last = history[history.length - 1];
      if (!last || (timestamp > last.ts && timestamp - last.ts >= sampleIntervalMs)) {
        history = [...history.slice(-(historyPoints - 1)), { ts: timestamp, value }];
      }
    }

    const isDark = theme === 'dark';
    const range = max - min;
    const isScaledK = min >= 0 && max >= 1000 && min % 1000 === 0 && max % 1000 === 0 && range <= 10000;
    let dialSplits = 5;
    let splitTicks = 2;
    if (isScaledK) {
      dialSplits = Math.round(range / 1000);
      splitTicks = 2;
    } else if (range === 100) {
      // Speed (0 - 100 MPH): 0, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100
      dialSplits = 10;
      splitTicks = 2;
    } else if (range === 160) {
      // Coolant & Trans fluid (100 - 260 °F): major ticks at 100, 140, 180, 220, 260
      dialSplits = 4;
      splitTicks = 2;
    } else if (range === 1200) {
      // EGT gauge (400 - 1600 °F): 400, 700, 1000, 1300, 1600 or 400, 600, 800, 1000, 1200, 1400, 1600
      dialSplits = 6;
      splitTicks = 2;
    } else if (range <= 10) {
      dialSplits = range;
      splitTicks = 2;
    } else if (range === 30) {
      // Boost (0 - 30 PSI): 0, 5, 10, 15, 20, 25, 30
      dialSplits = 6;
      splitTicks = 2;
    } else if (range % 200 === 0 && range / 200 <= 10) {
      dialSplits = Math.round(range / 200);
      splitTicks = 2;
    } else if (range % 100 === 0 && range / 100 <= 10) {
      dialSplits = Math.round(range / 100);
      splitTicks = 2;
    } else if (range % 50 === 0 && range / 50 <= 10) {
      dialSplits = Math.round(range / 50);
      splitTicks = 2;
    } else if (range % 20 === 0 && range / 20 <= 10) {
      dialSplits = Math.round(range / 20);
      splitTicks = 2;
    } else if (range % 10 === 0 && range / 10 <= 10) {
      dialSplits = Math.round(range / 10);
      splitTicks = 2;
    } else if (range <= 100) {
      dialSplits = 5;
      splitTicks = 2;
    }

    chart.setOption(type === 'sparkline' ? {
      animation: false,
      grid: { left: 2, right: 2, top: 5, bottom: 5 },
      xAxis: { type: 'category', show: false, data: history.map((_, index) => index) },
      yAxis: { type: 'value', show: false, min, max },
      series: [{ type: 'line', data: history.map((point) => point.value), symbol: 'none', smooth: true,
        lineStyle: { color, width: 2 }, areaStyle: { color, opacity: isDark ? 0.22 : 0.12 } }],
    } : type === 'dial' ? {
      series: [{
        type: 'gauge',
        min,
        max,
        splitNumber: dialSplits,
        startAngle: 225,
        endAngle: -45,
        radius: '92%',
        center: ['50%', '48%'],
        axisLine: {
          lineStyle: {
            width: 3,
            color: lowWarningBelow !== null ? [
              [(lowWarningBelow - min) / range, isDark ? '#f06459' : '#c6534b'],
              [1, isDark ? '#43685e' : '#4f6c62'],
            ] : [
              [0.8, isDark ? '#43685e' : '#4f6c62'],
              [1, isDark ? '#f06459' : '#c6534b'],
            ],
          },
        },
        progress: { show: false },
        splitLine: {
          show: true,
          distance: 0,
          length: 9,
          lineStyle: {
            color: 'auto',
            width: 2,
          },
        },
        axisTick: {
          show: true,
          splitNumber: splitTicks,
          distance: 0,
          length: 5,
          lineStyle: {
            color: 'auto',
            width: 1.2,
          },
        },
        axisLabel: {
          show: true,
          distance: 9,
          color: isDark ? '#e4eee9' : '#15362e',
          fontSize: range === 100 || range > 500 ? 9 : 10,
          fontWeight: 700,
          fontFamily: "'Space Grotesk', sans-serif",
          formatter: (v) => {
            if (isScaledK) return Math.round(v / 1000);
            return Math.round(v);
          },
        },
        title: {
          show: isScaledK,
          offsetCenter: [0, '34%'],
          color: isDark ? '#80a89a' : '#5b766c',
          fontSize: 10,
          fontWeight: 700,
          fontFamily: "'Space Grotesk', sans-serif",
        },
        pointer: {
          show: true,
          length: '72%',
          width: 3.5,
          itemStyle: { color: isDark ? '#f06459' : '#c6534b' },
        },
        anchor: {
          show: true,
          showAbove: true,
          size: 16,
          itemStyle: {
            color: isDark ? '#11221d' : '#163832',
            borderWidth: 2,
            borderColor: isDark ? '#38584f' : '#cadad3',
            shadowBlur: 4,
            shadowColor: isDark ? 'rgba(0,0,0,0.5)' : 'rgba(0,0,0,0.18)',
          },
        },
        detail: { show: false },
        data: [{
          value: typeof value === 'number' ? value : min,
          name: isScaledK ? '×1000' : '',
        }],
      }],
    } : {
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