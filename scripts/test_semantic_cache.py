"""语义缓存测试：验证同义命中/精确命中/不误命中。"""
import sys, json, os, tempfile
sys.path.insert(0, "src")

from cache.semantic_cache import SemanticCache

# 用临时文件，避免污染
tmp = os.path.join(tempfile.gettempdir(), "semcache_test.json")
if os.path.exists(tmp): os.remove(tmp)
cache = SemanticCache(tmp, capacity=8)

cache.store("土壤盐分超标怎么治理", "应灌水洗盐、排水排盐、增施有机肥。")
print("store 后条目数:", cache.stats()["entries"])

# 1) 精确重复 -> 应命中
print("\n[精确重复] 命中:", cache.lookup("土壤盐分超标怎么治理") is not None)

# 2) 同义改写 -> 应命中（语义）
print("[同义改写] '盐碱地怎么处理' 命中:", cache.lookup("盐碱地怎么处理") is not None)

# 3) 不同主题 -> 不应命中
print("[不同主题] '今天天气怎么样' 命中:", cache.lookup("今天天气怎么样") is not None)

# 4) 近义 -> 应命中
print("[近义改写] '土壤盐分超标应该怎么解决' 命中:", cache.lookup("土壤盐分超标应该怎么解决") is not None)

# 5) 持久化
cache.store("灌溉决策", "含水量低于60%需灌溉。")
cache2 = SemanticCache(tmp)
print("\n[持久化] 新实例读取条目数:", cache2.stats()["entries"])
os.remove(tmp)
