"""语义缓存（Semantic Cache）：对语义相似的问题复用缓存回答，避免重复调用 LLM/检索。

设计（面试炫技点）：
- 关键词缓存对"同义不同表述"无效（"怎么治盐碱" vs "盐碱地如何处理"），用 embedding 余弦
  相似度做语义命中，阈值 ≥ SIM_THRESHOLD 即复用。
- 命中时还能顺带命中"检索上下文"，连 embedding/检索的耗时一起省掉（端到端加速）。
- 带 LRU 容量上限 + 持久化到本地文件，重启不丢。

指标价值：命中率越高，LLM 调用越少，延迟越低、成本越低。
"""

from __future__ import annotations

import json
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from agents.sql_data_agent.embeddings import get_embedding_function, PROJECT_ROOT

SIM_THRESHOLD = 0.86  # 语义相似度命中阈值
DEFAULT_PATH = PROJECT_ROOT / "vector_store" / "semantic_cache.json"
_LOCK = threading.Lock()


@dataclass
class CacheEntry:
    query: str
    query_vec: list[float]
    answer: str
    ts: float


class SemanticCache:
    def __init__(self, path: str | Path = DEFAULT_PATH, capacity: int = 512):
        self.path = Path(path)
        self.capacity = capacity
        self._entries: list[CacheEntry] = []
        self._load()

    def _load(self) -> None:
        if self.path.exists():
            try:
                data = json.loads(self.path.read_text(encoding="utf-8"))
                self._entries = [
                    CacheEntry(**e) for e in data.get("entries", [])
                ]
            except Exception:  # noqa: BLE001
                self._entries = []

    def _persist(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            data = {"entries": [e.__dict__ for e in self._entries]}
            self.path.write_text(
                json.dumps(data, ensure_ascii=False, default=str), encoding="utf-8"
            )
        except Exception:  # noqa: BLE001 磁盘问题不致命
            pass

    def _vec(self, text: str) -> list[float]:
        fn = get_embedding_function()
        return fn.embed_query(text)

    def lookup(self, query: str) -> str | None:
        """按语义相似返回缓存的回答；未命中返回 None。"""
        if not self._entries:
            return None
        qv = self._vec(query)
        best, best_score = None, -1.0
        import math

        for e in self._entries:
            dot = sum(a * b for a, b in zip(qv, e.query_vec))
            na = math.sqrt(sum(x * x for x in qv))
            nb = math.sqrt(sum(x * x for x in e.query_vec))
            score = dot / (na * nb + 1e-9) if na and nb else 0.0
            if score > best_score:
                best_score, best = score, e.query
        if best is not None and best_score >= SIM_THRESHOLD:
            return next(e.answer for e in self._entries if e.query == best)
        return None

    def store(self, query: str, answer: str) -> None:
        """写入缓存（语义去重：已存在足够相似则更新而非追加）。"""
        with _LOCK:
            qv = self._vec(query)
            # 去重：若已有几乎相同 query，更新其 answer
            for e in self._entries:
                dot = sum(a * b for a, b in zip(qv, e.query_vec))
                na = (sum(x * x for x in qv)) ** 0.5
                nb = (sum(x * x for x in e.query_vec)) ** 0.5
                if dot / (na * nb + 1e-9) >= 0.99:
                    e.answer = answer
                    e.ts = time.time()
                    self._persist()
                    return
            self._entries.append(CacheEntry(query=query, query_vec=qv, answer=answer, ts=time.time()))
            # LRU：超容量则淘汰最旧的
            if len(self._entries) > self.capacity:
                self._entries.sort(key=lambda e: e.ts)
                self._entries = self._entries[-self.capacity:]
            self._persist()

    def stats(self) -> dict:
        return {"entries": len(self._entries), "path": str(self.path)}


# 全局默认实例
_default_cache: SemanticCache | None = None


def get_cache() -> SemanticCache:
    global _default_cache
    if _default_cache is None:
        _default_cache = SemanticCache()
    return _default_cache
