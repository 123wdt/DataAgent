"""图表输出：把查询结果转换为结构化 ECharts option（供前端渲染）。

设计：不依赖前端框架，输出纯 JSON 的 ECharts 配置。agent 在回答里可请求
生成折线图(趋势)/柱状图(对比)/饼图(占比)，由前端 agent-chat-ui / Vue 后台解析渲染。

工具：generate_chart(data: str, chart_type: str, x_field, y_field, title)
  - data     : 查询结果的 JSON 字符串（行字典列表）
  - chart_type: line / bar / pie
  - 返回 ECharts option JSON
"""

from __future__ import annotations

import json
import logging

from langchain_core.tools import tool

logger = logging.getLogger(__name__)


def _to_number(v) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _build_option(rows: list[dict], chart_type: str, x_field: str, y_field: str, title: str) -> dict:
    # 提取 X 轴与 Y 轴数据（数值非法跳过）
    xs, ys = [], []
    for r in rows:
        xv = r.get(x_field, "")
        yv = _to_number(r.get(y_field))
        xs.append(str(xv))
        ys.append(yv if yv is not None else 0)

    if chart_type == "line":
        series = [{"name": y_field, "type": "line", "smooth": True,
                   "data": ys, "areaStyle": {"opacity": 0.15}}]
    elif chart_type == "bar":
        series = [{"name": y_field, "type": "bar", "data": ys}]
    elif chart_type == "pie":
        # 饼图：value = 数值, name = X
        series = [{"name": title, "type": "pie", "radius": "60%",
                   "data": [{"name": str(x), "value": v} for x, v in zip(xs, ys)
                            if v is not None and v > 0]}]
    else:
        series = [{"name": y_field, "type": "line", "data": ys}]

    option = {
        "title": {"text": title, "left": "center"},
        "tooltip": {"trigger": "axis"},
        "legend": {"data": [y_field], "bottom": 0},
        "grid": {"left": 40, "right": 20, "top": 40, "bottom": 40},
        "xAxis": {"type": "category", "data": xs},
        "yAxis": {"type": "value", "name": y_field},
        "series": series,
    }
    if chart_type == "pie":
        option["tooltip"] = {"trigger": "item"}
        option.pop("xAxis", None)
        option.pop("yAxis", None)
        option["legend"] = {"orient": "vertical", "left": "left"}
    return option


@tool
def generate_chart(data: str, chart_type: str, x_field: str, y_field: str, title: str = "") -> str:
    """把查询结果生成 ECharts 折线图(line)/柱状图(bar)/饼图(pie)配置，返回 JSON。

    参数:
      data      : 查询结果 JSON（行字典数组）
      chart_type: line|bar|pie
      x_field   : X 轴字段名（如 record_time / station_name）
      y_field   : Y 轴数值字段名（如 humidity / salinity / rainfall）
      title     : 图表标题
    """
    try:
        rows = json.loads(data) if isinstance(data, str) else data
        if not rows or not isinstance(rows, list):
            return "图表数据为空"
    except json.JSONDecodeError as e:
        return f"数据 JSON 解析失败: {e}"

    option = _build_option(rows, chart_type, x_field, y_field, title or f"{y_field} {chart_type}")
    return json.dumps(option, ensure_ascii=False)
