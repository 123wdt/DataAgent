"""RAG-on-DDL 索引构建 + 检索冒烟测试。"""
import sys
sys.path.insert(0, "src")
from pathlib import Path
from agents.sql_data_agent.ddl import parse_create_tables
from agents.sql_data_agent.embeddings import build_index, search, DEFAULT_PERSIST

ddl = Path("scripts/db/schema.sql").read_text(encoding="utf-8")
cards = parse_create_tables(ddl)
print(f"解析到 {len(cards)} 张表卡片")
for c in cards:
    print(f"  - {c.table}: {c.comment} (字段{len(c.fields)})")

# 构建向量索引
from agents.sql_data_agent.embeddings import get_embedding_function
print("\n加载 embedding 模型并构建索引...")
build_index(cards, DEFAULT_PERSIST)
print("索引构建完成")

# 检索测试
print("\n=== 语义检索测试 ===")
for q in ["哪个地块土壤盐分超标", "北区平均含水量多少", "最近的气象降雨情况", "地下水水位多深"]:
    hits = search(q, k=3)
    print(f"\nQ: {q}")
    for h in hits:
        first = h.splitlines()[0] if h else ""
        print(f"   -> {first}")
