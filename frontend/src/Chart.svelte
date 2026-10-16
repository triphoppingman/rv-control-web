<script>
  import { onMount } from 'svelte';
  import * as echarts from 'echarts/core';
  import { CanvasRenderer } from 'echarts/renderers';

  echarts.use([CanvasRenderer]);

  export let options;
  export let line = false;

  let element;
  let chart;

  $: if (chart) chart.setOption(options, true);

  onMount(() => {
    chart = echarts.init(element);
    const observer = new ResizeObserver(() => chart.resize());
    observer.observe(element);
    return () => { observer.disconnect(); chart.dispose(); chart = null; };
  });
</script>

<div bind:this={element} class:line class="chart" aria-hidden="true"></div>
