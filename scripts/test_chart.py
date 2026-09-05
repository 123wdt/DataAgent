"""chart 模块冒烟测试。"""
import sys
sys.path.insert(0, "src")
import json
from agents.sql_data_agent.chart import generate_chart

data = [
    {"record_date": "2026-08-20", "rainfall": 3.4},
    {"record_date": "2026-08-21", "rainfall": 4.0},
    {"record_date": "2026-08-22", "rainfall": 0.2},
    {"record_date": "2026-08-23", "rainfall": 6.0},
]
opt = generate_chart.invoke({
    "data": json.dumps(data, ensure_ascii=False),
    "chart_type": "line",
    "x_field": "record_date",
    "y_field": "rainfall",
    "title": "北区气象站降雨趋势",
})
o = json.loads(opt)
print("折线图 option keys:", list(o.keys()))
print("series type:", o["series"][0]["type"], "| 点数:", len(o["series"][0]["data"]))
print("xAxis data:", o["xAxis"]["data"])

pie = generate_chart.invoke({
    "data": json.dumps([{"name": "北区", "value": 20.4}, {"name": "南区", "value": 8.7}]),
    "chart_type": "pie", "x_field": "name", "y_field": "value", "title": "区域降雨占比",
})
print("饼图 series type:", json.loads(pie)["series"][0]["type"])
print("图表工具 OK")
