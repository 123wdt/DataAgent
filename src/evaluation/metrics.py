"""自实现 RAG 三指标评测（轻量、可解释、复用本项目的 embedding，替代重量级 RAGAS）。

指标定义（对齐 RAGAS 语义）：
1. Faithfulness（忠实度）—— 回答是否忠于检索到的上下文，不编造。
   实现：把「回答中的每个断言句子」与「检索上下文」算语义相似度，取平均。
   越接近1说明回答越能从上下文得到支撑，越不容易幻觉。
2. Answer Relevance（回答相关性）—— 回答是否切题、回答了用户的问题。
   实现：把「问题嵌入」与「回答嵌入」算余弦相似度，衡量语义相关。
3. Context Precision（上下文精度）—— 检索到的上下文里，有多少是对回答"真正有用"的。
   实现：对每个检索命中的 chunk，判断其是否包含参考答案的关键词（命中的记为有用），
   用 RAGAS 的公式 AP = Σ(Precision@k × relevancy_k) / 有用文档总数。

全部为 0~1 分数，越高越好。
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Callable

from agents.sql_data_agent.embeddings import get_embedding_function

# 真实的 Embedder：把文本批量编码为向量
def _embed_texts(texts: list[str]) -> list[list[float]]:
    fn = get_embedding_function()
    return fn.embed_documents(texts)


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    return dot / (na * nb + 1e-9)


def _split_sentences(text: str) -> list[str]:
    """把回答切成断言句子（按中文句号/分号/换行切分）。"""
    parts = re.split(r"[。；;\n]+", text)
    return [p.strip() for p in parts if len(p.strip()) > 2]


# ---------------------------------------------------------------------------
# 指标 1：Faithfulness（忠实度）
# ---------------------------------------------------------------------------
def faithfulness(answer: str, contexts: list[str]) -> float:
    """回答断言能被检索上下文支撑的比例（语义相似度均值）。"""
    sent_vecs = _embed_texts(_split_sentences(answer)) if answer.strip() else []
    if not sent_vecs:
        return 0.0
    ctx_vecs = _embed_texts(contexts)
    if not ctx_vecs:
        return 0.0
    scores = []
    for s in sent_vecs:
        best = max(cosine(s, c) for c in ctx_vecs)
        scores.append(best)
    return sum(scores) / len(scores)


# ---------------------------------------------------------------------------
# 指标 2：Answer Relevance（回答相关性）
# ---------------------------------------------------------------------------
def answer_relevance(question: str, answer: str) -> float:
    """问题与回答的语义相关度（余弦相似度）。"""
    if not answer.strip():
        return 0.0
    q, a = _embed_texts([question, answer])
    return cosine(q, a)


# ---------------------------------------------------------------------------
# 指标 3：Context Precision（上下文精度）
# ---------------------------------------------------------------------------
def _norm(s: str) -> str:
    """去掉空白做归一化，避免 '30-50 mm' 与 '30-50mm' 匹配失败。"""
    return re.sub(r"\s+", "", s)


def context_precision(contexts: list[str], reference_keywords: list[str], k: int | None = None) -> float:
    """检索命中的上下文里，对回答有用的占比（RAGAS 风格 AP 公式）。"""
    if not contexts:
        return 0.0
    k = k or len(contexts)
    norm_kws = [_norm(kw) for kw in reference_keywords]
    relevant_flags = []
    for ctx in contexts[:k]:
        # 上下文是否包含参考答案的关键词（判定"是否有用"）
        nc = _norm(ctx)
        hit = any(kw and kw in nc for kw in norm_kws)
        relevant_flags.append(hit)
    total_relevant = sum(relevant_flags)
    if total_relevant == 0:
        return 0.0
    ap = 0.0
    for i, rel in enumerate(relevant_flags):
        if rel:
            ap += sum(relevant_flags[: i + 1]) / (i + 1)
    return ap / total_relevant


@dataclass
class SampleResult:
    question: str
    faithfulness: float
    answer_relevance: float
    context_precision: float


@dataclass
class EvalReport:
    """一份评测报告（看板数据）。"""
    metrics: dict[str, float] = field(default_factory=dict)  # 平均分
    samples: list[SampleResult] = field(default_factory=list)
    n: int = 0


def evaluate_knowledge_agent(
    agent,
    dataset: list[dict],
    retriever=None,
    llm_answer=None,
) -> EvalReport:
    """对知识 Agent 跑评测闭环。

    agent: 可调用对象，输入 question 返回回答文本。
    retriever: 可选，输入 question 返回 context 文本列表（缺省用 knowledge_search）。
    """
    report = EvalReport()
    for item in dataset:
        q = item["question"]
        answer = llm_answer(q)
        # 检索上下文
        ctxs = []
        if retriever is not None:
            raw = retriever(q)
            ctxs = [r["text"] for r in raw] if isinstance(raw, list) else [raw]
        else:
            from agents.knowledge_agent.kb import knowledge_search

            ctxs = [r["text"] for r in knowledge_search(q, k=5)]

        f = faithfulness(answer, ctxs)
        ar = answer_relevance(q, answer)
        cp = context_precision(ctxs, item.get("relevant_keywords", []))

        report.samples.append(SampleResult(question=q, faithfulness=f, answer_relevance=ar, context_precision=cp))
        report.n += 1

    # 汇总平均
    report.metrics = {
        "faithfulness": round(sum(s.faithfulness for s in report.samples) / report.n, 4),
        "answer_relevance": round(sum(s.answer_relevance for s in report.samples) / report.n, 4),
        "context_precision": round(sum(s.context_precision for s in report.samples) / report.n, 4),
    }
    return report
