<script>
  import * as echarts from 'echarts/core';
  import { GaugeChart } from 'echarts/charts';
  import Chart from './Chart.svelte';

  echarts.use([GaugeChart]);

  export let value = null;
  export let min = 0;
  export let max = 100;
  export let theme = 'light';
  export let lowWarningBelow = null;
  export let showWarning = true;

  let dialSplits;

  $: isDark = theme === 'dark';
  $: range = max - min;
  $: isScaledK = min >= 0 && max >= 1000 && min % 1000 === 0 && max % 1000 === 0 && range <= 10000;
  $: {
    dialSplits = 5;
    if (isScaledK) {
      dialSplits = Math.round(range / 1000);
    } else if (range === 100) {
      dialSplits = 10;
    } else if (range === 160) {
      dialSplits = 4;
    } else if (range === 1200) {
      dialSplits = 6;
    } else if (range <= 10) {
      dialSplits = range;
    } else if (range === 30) {
      dialSplits = 6;
    } else {
      for (const step of [200, 100, 50, 20, 10]) {
        if (range % step === 0 && range / step <= 10) {
          dialSplits = Math.round(range / step);
          break;
        }
      }
    }
  }
  $: options = {
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
          color: !showWarning ? [[1, isDark ? '#43685e' : '#4f6c62']] : lowWarningBelow !== null ? [
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
        lineStyle: { color: 'auto', width: 2 },
      },
      axisTick: {
        show: true,
        splitNumber: 2,
        distance: 0,
        length: 5,
        lineStyle: { color: 'auto', width: 1.2 },
      },
      axisLabel: {
        show: true,
        distance: 9,
        color: isDark ? '#e4eee9' : '#15362e',
        fontSize: range === 100 || range > 500 ? 9 : 10,
        fontWeight: 700,
        fontFamily: "'Space Grotesk', sans-serif",
        formatter: (v) => isScaledK ? Math.round(v / 1000) : Math.round(v),
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
  };
</script>

<Chart {options} />
