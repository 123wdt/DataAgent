"""BizAgent 查数 Agent 数据访问层。

只读安全三层设计：
  1. 连接层：统一用只读账号 bizagent_ro（PostgreSQL 侧仅授予 SELECT）
  2. 语句层：SQL 校验器只允许 SELECT 开头、拒绝 DDL/DML/危险关键字
  3. 结果层：限制返回行数 / 查询超时，避免资源耗尽与注入拖库

本模块屏蔽底层驱动（psycopg3），对外提供：
  - query(sql) -> list[dict]       执行只读查询，返回行字典
  - get_schema_whitelist()         允许访问的表清单（业务语义白名单）
"""

from __future__ import annotations

import logging
import time
from typing import Any

import psycopg
from psycopg.rows import dict_row

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# 连接配置（只读账号，安全基线见 skills/bizagent simulation-db reference）
# ---------------------------------------------------------------------------
DB_HOST = "localhost"
DB_PORT = 5433
DB_NAME = "bizagent"
DB_USER = "bizagent_ro"
DB_PASS = "bizagent_ro_2026"

# 业务语义白名单：agent 只能触及这些表（对齐 schema.sql 定义的业务模型）
SCHEMA_WHITELIST: frozenset[str] = frozenset(
    {
        "region_zone",          # 区域（北区/南区）
        "region_patch",         # 地块（1~6号）
        "mon_station",          # 站点（墒情/气象/地下水/pH）
        "mon_soil_record",      # 土壤墒情（湿度/盐分）
        "mon_weather_record",   # 气象（温度/湿度/风速/降雨）
        "mon_groundwater_record",  # 地下水位
        "mon_ph_record",        # pH
        "alert_threshold",      # 预警阈值
        "alert_soil_log",       # 预警日志
        "irri_control",         # 灌溉控制
        "irri_fertilizer_tank", # 施肥罐
    }
)

# 每查询最大返回行数（防拖库 / 防 token 爆炸）
MAX_ROWS = 500
# 单查询超时（秒）
QUERY_TIMEOUT = 10

_pool: psycopg.AsyncConnectionPool | None = None


def _get_pool() -> psycopg.AsyncConnectionPool:
    global _pool
    if _pool is None:
        _pool = psycopg.AsyncConnectionPool(
            conninfo=(
                f"host={DB_HOST} port={DB_PORT} dbname={DB_NAME} "
                f"user={DB_USER} password={DB_PASS} connect_timeout=5"
            ),
            min_size=1,
            max_size=5,
            kwargs={"row_factory": dict_row},
        )
    return _pool


def get_schema_whitelist() -> list[str]:
    """返回允许访问的表清单（供 RAG-on-DDL 与 SQL 校验共用）。"""
    return sorted(SCHEMA_WHITELIST)


def query(sql: str, params: Any = None, max_rows: int = MAX_ROWS) -> list[dict]:
    """执行只读查询，返回行字典列表。

    说明：同步封装（psycopg3 同步连接），供 ReAct 工具节点同步调用。
    SQL 必须先经过 safe_sql.validate_sql() 校验。
    """
    start = time.perf_counter()
    with psycopg.connect(
        f"host={DB_HOST} port={DB_PORT} dbname={DB_NAME} "
        f"user={DB_USER} password={DB_PASS} connect_timeout=5",
        row_factory=dict_row,
    ) as conn:
        with conn.cursor() as cur:
            cur.execute(f"SET statement_timeout = {QUERY_TIMEOUT * 1000}")
            if params:
                cur.execute(sql, params)
            else:
                cur.execute(sql)
            cols = [d.name for d in cur.description] if cur.description else []
            rows = cur.fetchmany(max_rows + 1)
            truncated = len(rows) > max_rows
            rows = rows[:max_rows]
    elapsed = (time.perf_counter() - start) * 1000
    logger.info("query ok: %.0fms rows=%d truncated=%s :: %s", elapsed, len(rows), truncated, sql[:80])
    result = [dict(r) for r in rows]
    if truncated:
        result.append({"_truncated": True})
    return result
