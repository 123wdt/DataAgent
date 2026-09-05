"""查数 Agent 的工具集（LangChain tools）。

工具清单：
  - RetrieveDDL   ：RAG-on-DDL 检索 —— 根据业务问题找出要用的表（元数据层）
  - RunSQL        ：只读执行 SQL（安全三层 + 结果行数限制）
  - ListTables    ：列出业务白名单内的表（引导 LLM 选表）
  - ResolveEntity ：地名/站点/时序词解析（把"3号地块/北区/昨天"映射为查询条件）
"""

from __future__ import annotations

import logging
import re
from datetime import date, datetime, timedelta

from langchain_core.tools import tool

from agents.sql_data_agent.db import get_schema_whitelist, query
from agents.sql_data_agent.embeddings import search as rag_search
from agents.sql_data_agent.safe_sql import (
    ValidationResult,
    check_tables_in_whitelist,
    validate_sql,
)

logger = logging.getLogger(__name__)


@tool
def retrieve_ddl(question: str) -> str:
    """根据用户的业务问题，检索并返回相关的数据库表结构卡片（表、字段、单位、枚举、外键）。

    在生成 SQL 之前先调用这个工具，找到"该用哪些表"。返回的多张表卡片可作为 SQL 生成的依据。
    """
    cards = rag_search(question, k=5)
    if not cards:
        return "未检索到相关表，请先执行 build_rag_ddl_index 构建索引。"
    return "\n\n=====\n\n".join(cards)


@tool
def list_tables() -> str:
    """返回当前数据库允许访问的所有业务表清单（供选择用哪张表）。"""
    return "可用表: " + ", ".join(get_schema_whitelist())


@tool
def run_sql(sql: str) -> str:
    """执行一条只读 SQL 查询并返回结果（JSON 行）。仅允许 SELECT，且只能访问业务白名单表。

    当需要按时间/站点/区域过滤时，自行在 SQL 的 WHERE 里写条件（参考 ResolveEntity 解析出的条件）。
    """
    # 安全三层：先校验语法与版权，再查白名单
    v1: ValidationResult = validate_sql(sql)
    if not v1.ok:
        return f"SQL 被拒绝：{v1.reason}"
    v2: ValidationResult = check_tables_in_whitelist(sql)
    if not v2.ok:
        return f"SQL 被拒绝：{v2.reason}"

    import json

    try:
        rows = query(sql)
    except Exception as e:  # noqa: BLE001
        return f"查询执行失败：{e}"

    if not rows:
        return "查询返回 0 行"
    truncated = any("_truncated" in r for r in rows)
    rows = [r for r in rows if "_truncated" not in r]
    text = json.dumps(rows, ensure_ascii=False, default=str)[:6000]
    if truncated:
        text += "\n[结果已截断，仅显示前若干行]"
    return text


# ---------------------------------------------------------------------------
# 实体解析：把自然语言里的时间/地点/站点词翻译成可用于 SQL 的条件
# ---------------------------------------------------------------------------
# 中文数字 -> 阿拉伯数字
_CN_NUM = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
           "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}


@tool
def resolve_entity(text: str) -> str:
    """把用户话里的名称/时间解析成结构化条件（JSON）：{tables, conditions, hint}。

    例如"3号地块"→地块名=3号地块；"北区"→区域=北区；"昨天/近7天/最近一星期"→时间范围。
    用在生成 WHERE 条件之前的解析步骤。返回 JSON 给 SQL 生成参考。
    """
    conds: dict = {}
    tables: set[str] = set()

    # ----- 区域/地块/站点解析 -----
    zone_m = re.search(r"(北区|南区)", text)
    if zone_m:
        conds["zone_name"] = zone_m.group(1)
        tables.add("region_zone")
    patch_m = re.search(r"(\d+|[一二两三四五六七八九十]+)号\s*地块", text)
    if patch_m:
        conds["patch_name"] = f"{patch_m.group(1)}号地块"
        tables.add("region_patch")
    st_m = re.search(r"(\d+|[一二两三四五六七八九十]+)号\s*(墒情|气象|地下水|ph|pH)?站", text)
    if st_m:
        num = st_m.group(1)
        if num in _CN_NUM:
            num = str(_CN_NUM[num])
        stype = st_m.group(2)
        conds["station_hint"] = f"{num}号{'墒情站' if stype in (None,'墒情') else stype+'站'}"
        tables.update({"mon_station", "mon_soil_record"})

    # ----- 时间解析 -----
    today = date.today()
    days = None
    if re.search(r"今天|今日", text):
        conds["time_start"], conds["time_end"] = str(today), str(today)
    elif re.search(r"昨天|昨日", text):
        d = today - timedelta(days=1)
        conds["time_start"], conds["time_end"] = str(d), str(d)
    else:
        m7 = re.search(r"近?\s*(\d+)\s*天", text)
        mw = re.search(r"近?\s*(?:一|1)\s*(?:周|星期)|最近\s*(?:一周|一星期)", text)
        m_week = re.search(r"近?\s*(\d+)\s*(?:周|星期)", text)
        if m7:
            days = int(m7.group(1))
        elif m_week:
            days = int(m_week.group(1)) * 7 if m_week.group(1) != "一" and m_week.group(1) != "1" else 7
        elif mw:
            days = 7
        if days:
            conds["time_start"] = str(today - timedelta(days=days))
            conds["time_end"] = str(today)
    if "time_start" in conds:
        tables.update({"mon_soil_record", "mon_weather_record"})

    # ----- 指标解析（提示用哪个字段） -----
    metric = None
    for kw, field in [("盐分", "salinity"), ("含水量", "humidity"), ("湿度", "humidity"),
                      ("温度", "temperature"), ("降雨", "rainfall"), ("风速", "wind_speed"),
                      ("地下水位", "depth"), ("PH", "ph"), ("pH", "ph"), ("电导率", "ec")]:
        if kw.lower() in text.lower():
            metric = field
            break
    if metric:
        conds["metric"] = metric

    hint = "可据此在 SQL 中构造 WHERE。若无明确时间/地点，用最近记录即可。"
    import json
    return json.dumps({"tables": sorted(tables), "conditions": conds, "hint": hint},
                      ensure_ascii=False)
