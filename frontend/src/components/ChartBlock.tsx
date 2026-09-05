// 图表组件：渲染 sql-data-agent 返回的 ECharts 图表 JSON
import { useEffect, useRef } from "react";
import * as echarts from "echarts";

interface ChartBlockProps {
  option: any;
  height?: number;
}

export default function ChartBlock({ option, height = 300 }: ChartBlockProps) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!ref.current) return;
    const chart = echarts.init(ref.current);
    try {
      chart.setOption(option);
    } catch (e) {
      console.error("图表渲染失败", e);
    }
    const onResize = () => chart.resize();
    window.addEventListener("resize", onResize);
    return () => {
      window.removeEventListener("resize", onResize);
      chart.dispose();
    };
  }, [option]);

  return <div ref={ref} style={{ width: "100%", height }} />;
}
