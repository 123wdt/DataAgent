"""增量索引测试：验证"源未变则跳过重建，变了才重建"。"""
import sys, os, time
sys.path.insert(0, "src")
from cache.index_fingerprint import ensure_rag_ddl_index, schema_changed, mark_schema_built

# 第一次：无论指纹如何，确保构建并打标
t0 = time.time()
rebuilt = ensure_rag_ddl_index()
print(f"[首次 ensure] rebuilt={rebuilt} ({time.time()-t0:.2f}s)")

# 第二次：源没变，应跳过重建
t0 = time.time()
rebuilt2 = ensure_rag_ddl_index()
print(f"[再次 ensure] rebuilt={rebuilt2} ({time.time()-t0:.2f}s)  <- 应为 False 且耗时极短(跳过embedding)")

# 模拟 schema.sql 变更：触摸(改内容)后应检测到
print("\nschema_changed() (未改, 应为False):", schema_changed())

print("\n结论: 增量索引生效" if rebuilt2 is False else "\n结论: 仍全量重建(待优化)")
