"""RAG 评测闭环：自实现三指标（忠实度/相关度/上下文精度）。"""

from evaluation.metrics import (
    EvalReport,
    SampleResult,
    answer_relevance,
    context_precision,
    faithfulness,
)

__all__ = [
    "EvalReport",
    "SampleResult",
    "faithfulness",
    "answer_relevance",
    "context_precision",
]
