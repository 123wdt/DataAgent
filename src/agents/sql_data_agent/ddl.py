"""RAG-on-DDL：把建表 DDL 解析为"DDL 卡片"并向量化。

差异化设计（面试点）：不把全量 DDL 塞进 prompt（token 浪费且难检索），而是
把每张业务表解析成一条结构化 DDL 卡片 —— 表名 + 业务注释 + 关键字段 + 单位 +
枚举值 + 主外键关系。查询时先向量检索"该用哪张表"，再把命中表的卡片喂给
LLM 生成 SQL。降低幻觉、压缩上下文、可溯源。

对账单页数据的另一层作用：卡片同时作为 GraphRAG 的节点元数据底座。
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# 数值字段单位映射（来自 schema.sql 字段注释 / 业务常识）
UNIT_MAP = {
    "humidity": "%", "salinity": "g/kg", "temperature": "℃", "wind_speed": "m/s",
    "rainfall": "mm", "evaporation": "mm", "sun_hours": "h", "depth": "m",
    "ec": "µS/cm", "capacity": "L", "current_level": "L",
    "water_amount": "m³", "fert_amount": "kg", "soil_moisture": "%",
}

# 纯类型关键字（用于剥离字段类型串中的杂项）
_SIMPLE_TYPES = {"bigint", "integer", "smallint", "numeric", "timestamp", "date",
                 "varchar", "text", "serial", "bigserial", "boolean", "real", "double"}


@dataclass
class FieldInfo:
    name: str
    type: str
    comment: str = ""
    unit: str = ""
    enum: list[str] = field(default_factory=list)


@dataclass
class TableCard:
    table: str            # 表名
    comment: str = ""     # 表级业务说明
    fields: list[FieldInfo] = field(default_factory=list)
    pk: str = ""
    fk: dict[str, str] = field(default_factory=dict)  # 外键字段 -> 引用表

    @property
    def text(self) -> str:
        """渲染为可向量化/可喂给 LLM 的文本卡片。"""
        lines = [f"表: {self.table}  ({self.comment})", f"主键: {self.pk}"]
        for f in self.fields:
            extra = f" 单位:{f.unit}" if f.unit else ""
            enum_part = f" 枚举:{'/'.join(f.enum)}" if f.enum else ""
            cmt = f" 含义:{f.comment}" if f.comment else ""
            lines.append(f"  - {f.name} {f.type}{extra}{enum_part}{cmt}")
        if self.fk:
            lines.append("外键: " + ", ".join(f"{k}->{v}" for k, v in self.fk.items()))
        return "\n".join(lines)


def _clean_type(t: str) -> str:
    """清理类型串，去掉 PRIMARY KEY/NOT NULL/DEFAULT 等约束词，保留类型+长度。"""
    t = t.strip()
    # 去掉 DEFAULT、NOT NULL、REFERENCES、PRIMARY KEY、UNIQUE 等
    t = re.split(r"\s+(?:primary\s+key|not\s+null|references|default|unique|check)\b", t, flags=re.I)[0]
    # 去掉尾随逗号
    t = t.rstrip(",").strip()
    # 去掉 'xx' 默认值
    t = re.sub(r"'[^']*'$", "", t).rstrip().rstrip(",")
    return t.strip()


def parse_create_tables(ddl_text: str) -> list[TableCard]:
    """从整段建表 DDL 解析所有表卡片（含表注释 = CREATE TABLE 上一行 -- 注释）。"""
    cards: list[TableCard] = []
    # 用正则匹配 "CREATE TABLE name (\n ... );"，连同前置注释行一起捕获
    # pattern: (?m)(^--\s*[^\n]*\n)?\s*CREATE TABLE\s+(\w+)\s*\((.*?)\)\s*;
    pat = re.compile(
        r"(?m)(^--\s*[^\n]*\n)?\s*CREATE\s+TABLE\s+(\w+)\s*\((.*?)\)\s*;",
        re.I | re.S,
    )
    for m in pat.finditer(ddl_text):
        pre_comment = m.group(1)
        table = m.group(2)
        body = m.group(3)
        comment = ""
        if pre_comment:
            comment = pre_comment.strip()[2:].strip()  # 去掉 '-- '
        cards.append(_parse_body(table, body, comment))
    return cards


def _parse_body(table: str, body: str, comment: str) -> TableCard:
    card = TableCard(table=table, comment=comment)
    pk = ""
    fks: dict[str, str] = {}

    for line in body.splitlines():
        line = line.strip()
        if not line or line == ")":
            continue

        # 表级约束行
        if re.match(r"^PRIMARY\s+KEY", line, re.I):
            m = re.search(r"\((.*?)\)", line)
            if m:
                pk = m.group(1).strip()
            continue
        if re.match(r"^(CONSTRAINT\s+\w+\s+)?FOREIGN\s+KEY", line, re.I):
            col = re.search(r"FOREIGN\s+KEY\s*\((\w+)\)\s*REFERENCES\s+(\w+)", line, re.I)
            if col:
                fks[col.group(1)] = col.group(2)
            continue
        if re.match(r"^(CONSTRAINT|UNIQUE|CHECK)", line, re.I):
            continue

        # 列定义行：name type ... [-- 注释]
        col_m = re.match(r"([a-zA-Z_]\w*)\s+([a-zA-Z][\w, ()]*)\s*(.*)", line)
        if not col_m:
            continue
        fname = col_m.group(1)
        raw_rest = col_m.group(3)

        # 区分枚举与注释：优先看是否有 REFERENCES / IN
        # 提取外键
        ref_m = re.search(r"REFERENCES\s+(\w+)", line, re.I)
        if ref_m:
            fks[fname] = ref_m.group(1)

        # 枚举 IN (...)
        enum = []
        in_m = re.search(r"IN\s*\((.*?)\)", line, re.I | re.S)
        if in_m:
            enum = re.findall(r"'([^']*)'", in_m.group(1))[:6]

        # 列注释（-- 之后非枚举文本）
        fcomment = ""
        cm_m = re.search(r"--\s*([^\n]+)", line)
        if cm_m:
            cm_txt = cm_m.group(1).strip()
            # 如果注释内容看起来是枚举值列表（斜杠/空格分隔的短词），跳过当作枚举
            if not re.match(r"^[a-z_]+(?:\s*/\s*[a-z_]+)+$", cm_txt.lower()):
                fcomment = cm_txt

        # 清理类型
        ftype = _clean_type(col_m.group(2))
        unit = UNIT_MAP.get(fname.lower(), "")
        card.fields.append(FieldInfo(fname, ftype, fcomment, unit, enum))

    card.pk = pk
    card.fk = fks
    return card
