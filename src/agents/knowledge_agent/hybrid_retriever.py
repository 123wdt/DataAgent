"""混合检索器：向量(语义) + BM25(关键词) 双路召回 + RRF 融合。

设计（面试炫技点 A1）：
- 只靠向量检索，农业领域专有词/数字阈值（"g/kg"、"压盐"、"暗管"）召回不稳；
  BM25 精确匹配这些关键词，弥补向量对低频专业词的短板。
- RRF(Reciprocal Rank Fusion)：对两路排序做加权融合，
  score = sum(1/(k + rank_i))，不依赖分数可比性，稳健且无需调参到两路分数同量纲。
- 归一化 + 可选阈值过滤。

轻量实现：纯 fastembed(onnx) + 自实现 BM25，无重型依赖，本地可跑。
"""

from __future__ import annotations

import logging
import re
from typing import Callable

logger = logging.getLogger(__name__)

# 中文分词：按非中英文/数字字符切分，保留中文单字与英文/数字词
_TOKEN_RE = re.compile(r"[\u4e00-\u9fff]|[a-zA-Z0-9]+")


def tokenize(text: str) -> list[str]:
    """极简中文+英文/数字分词。中文按单字、英文按词、数字保留。"""
    return _TOKEN_RE.findall(text)


class BM25:
    """Okapi BM25 关键词检索（自实现，避免重型依赖）。

    用 IDF 权重衡量词的重要度，专业词（出现于少数文档）权重高。
    """

    def __init__(self, corpus: list[str], k1: float = 1.5, b: float = 0.75):
        self.k1 = k1
        self.b = b
        self.docs: list[list[str]] = [tokenize(d) for d in corpus]
        self.doc_len = [len(d) for d in self.docs]
        self.avgdl = sum(self.doc_len) / len(self.docs) if self.docs else 0.0
        self.doc_freq: dict[str, int] = {}  # 词 -> 出现文档数
        for toks in self.docs:
            for t in set(toks):
                self.doc_freq[t] = self.doc_freq.get(t, 0) + 1
        self.N = len(self.docs)

    def score(self, query: str, doc_idx: int) -> float:
        q_tokens = set(tokenize(query))
        if not q_tokens:
            return 0.0
        dl = self.doc_len[doc_idx]
        score = 0.0
        for t in q_tokens:
            df = self.doc_freq.get(t, 0)
            if df == 0:
                continue
            idf = log_1plus((self.N - df + 0.5) / (df + 0.5))
            # 词频
            tf = self.docs[doc_idx].count(t)
            denom = tf + self.k1 * (1 - self.b + self.b * dl / self.avgdl)
            score += idf * (tf * (self.k1 + 1)) / (denom if denom else 1e-9)
        return score

    def search(self, query: str, k: int = 8) -> list[tuple[int, float]]:
        scored = [(i, self.score(query, i)) for i in range(self.N)]
        scored.sort(key=lambda x: x[1], reverse=True)
        return [(i, s) for i, s in scored if s > 0][:k]


def log_1plus(x: float) -> float:
    import math

    return math.log(1.0 + x) if x > 0 else 0.0


def rrf_fuse(
    vector_rank: list[tuple[int, float]],
    bm25_rank: list[tuple[int, float]],
    k: int = 60,
    limit: int = 6,
) -> list[tuple[int, float]]:
    """Reciprocal Rank Fusion 融合两路排序。返回 top-limit 的 (doc_idx, fused_score)。"""
    import math

    scores: dict[int, float] = {}
    for rank, (idx, _) in enumerate(vector_rank):
        scores[idx] = scores.get(idx, 0.0) + 1.0 / (k + rank + 1)
    for rank, (idx, _) in enumerate(bm25_rank):
        scores[idx] = scores.get(idx, 0.0) + 1.0 / (k + rank + 1)
    fused = sorted(scores.items(), key=lambda x: x[1], reverse=True)
    return fused[:limit]


class HybridRetriever:
    """向量 + BM25 + RRF 的统一检索器。"""

    def __init__(
        self,
        chunks: list[str],
        embed_fn: Callable[[list[str]], list[list[float]]],
    ):
        self.chunks = chunks
        self.bm25 = BM25(chunks)
        self.embed_fn = embed_fn
        # 一次性编码所有 chunk 并缓存，避免每次检索重复调用 embedding
        self._chunk_vecs: list[list[float]] | None = None

    def _chunk_vectors(self) -> list[list[float]]:
        if self._chunk_vecs is None:
            self._chunk_vecs = list(self.embed_fn(self.chunks))
        return self._chunk_vecs

    def hybrid_search(self, query: str, k: int = 6) -> list[dict]:
        """返回 [{'id': int, 'text': str, 'score': float}]，已按融合分排序。"""
        # 向量路召回（余弦相似度）
        q_vec = self.embed_fn([query])[0]
        vec_scores = [
            (i, cosine_sim(q_vec, cvec)) for i, cvec in enumerate(self._chunk_vectors())
        ]
        vec_scores.sort(key=lambda x: x[1], reverse=True)
        vec_rank = [(i, s) for i, s in vec_scores[: k * 3]]

        bm25_rank = self.bm25.search(query, k=k * 3)

        fused = rrf_fuse(vec_rank, bm25_rank, limit=k)
        results = []
        for idx, score in fused:
            results.append({"id": idx, "text": self.chunks[idx], "score": round(float(score), 4)})
        return results


def cosine_sim(a: list[float], b: list[float]) -> float:
    import math

    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb + 1e-9)
