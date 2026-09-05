"""SQL 生成结果的安全校验器（NL2SQL 只读安全第二层）。

职责（在 SQL 提交执行前强制拦截）：
  - 只允许单条 SELECT 语句（拒绝多语句 / 分号注入 / 注释绕过）
  - 出现任何写操作关键字（INSERT/UPDATE/DELETE/DROP/ALTER/CREATE/...）直接拒绝
  - 访问的表必须在业务白名单内（防枚举系统表 information_schema/pg_*）
  - 可选注入参数化（先做关键字级防御，参数化在 NL2SQL 里留作后续增强）
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from agents.sql_data_agent.db import SCHEMA_WHITELIST

# 写操作 / 危险语句关键字（必须整词匹配，避免误伤列名如 update_time）
_DANGEROUS_KEYWORDS = [
    r"\binsert\b", r"\bupdate\b", r"\bdelete\b", r"\bdrop\b", r"\balter\b",
    r"\bcreate\b", r"\btruncate\b", r"\bgrant\b", r"\brevoke\b", r"\breplace\b",
    r"\bmerge\b", r"\bcopy\b", r"\bvacuum\b", r"\bload\b", r"\bcall\b",
    r"\bexec\b", r"\bexecute\b", r"\bdo\b", r"\breturn\b", r"\bdeclare\b",
]
_DANGEROUS_RE = re.compile("|".join(_DANGEROUS_KEYWORDS), re.IGNORECASE)

# 危险 SQL 片段（含 -- 注释、分号注入、堆叠语句）
_INJECTION_PATTERNS = [
    re.compile(r"^\s*;", re.I),                    # 开头分号
    re.compile(r";\s*\w", re.I),                   # 语句间分号（堆叠）
    re.compile(r"--"),                             # 注释
    re.compile(r"/\*"),                            # 块注释
    re.compile(r"information_schema", re.I),
    re.compile(r"\bpg_[a-z_]+\b"),                 # pg 系统表/函数
]

# 只允许以这些关键字之一开始（宽容：允许 with/select；LLM 输出的前导空白）
_ALLOWED_PREFIX = re.compile(r"^\s*(select|with)\b", re.I)


@dataclass
class ValidationResult:
    ok: bool
    reason: str = ""
    sql: str = ""


def validate_sql(sql: str) -> ValidationResult:
    """校验 LLM 生成的 SQL，通过返回 ok=True，否则给出拒绝原因。"""
    if not sql or not sql.strip():
        return ValidationResult(False, "SQL 为空")

    # 1) 前缀检查：必须是 SELECT / WITH
    if not _ALLOWED_PREFIX.match(sql):
        return ValidationResult(False, "只允许 SELECT 查询语句")

    # 2) 危险关键字检查（去掉 SELECT 之后全文都查）
    if _DANGEROUS_RE.search(sql):
        return ValidationResult(False, f"检测到被禁止的关键字: {_DANGEROUS_RE.search(sql).group()}")

    # 3) 注入片段检查
    for pat in _INJECTION_PATTERNS:
        if pat.search(sql):
            return ValidationResult(False, f"检测到风险片段: {pat.pattern}")

    return ValidationResult(True, sql=sql)


def extract_tables(sql: str) -> set[str]:
    """从 SQL 中提取提到的表名（用于白名单校验）。"""
    found = set()
    # 匹配 from/join/update/into 后的标识符
    for m in re.finditer(r"\b(?:from|join)\s+([a-zA-Z_][a-zA-Z0-9_]*)", sql, re.I):
        found.add(m.group(1).lower())
    return found


def check_tables_in_whitelist(sql: str) -> ValidationResult:
    """检查 SQL 引用的所有表都在业务白名单内。"""
    tables = extract_tables(sql)
    if not tables:
        return ValidationResult(False, "SQL 未引用任何表")
    bad = tables - SCHEMA_WHITELIST
    if bad:
        return ValidationResult(False, f"访问了白名单外的表: {sorted(bad)}")
    return ValidationResult(True, sql=sql)
