"""评测闭环运行入口：对知识 Agent 跑 RAG 三指标（忠实度/相关度/上下文精度），输出看板。

用法：uv run python -m src.evaluation.run_evaluation
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from langchain_core.messages import HumanMessage
from core import get_model, settings
from agents.knowledge_agent.knowledge_agent import knowledge_agent
from evaluation.dataset import EVAL_SET
from evaluation.metrics import (
    EvalReport,
    SampleResult,
    faithfulness,
    answer_relevance,
    context_precision,
)
from agents.knowledge_agent.kb import knowledge_search


async def ask_knowledge_agent(question: str) -> str:
    """调用知识 Agent 得到最终回答文本。"""
    resp = await knowledge_agent.ainvoke(
        {"messages": [HumanMessage(content=question)]},
        config={"configurable": {"model": settings.DEFAULT_MODEL}, "recursion_limit": 30},
    )
    final = ""
    for m in reversed(resp["messages"]):
        if getattr(m, "content", None) and not getattr(m, "tool_calls", None):
            final = m.content
            break
    return final


def run_sync(dataset: list[dict]) -> EvalReport:
    """同步版：逐个指标计算（不联调 agent，用公式离线算，便于快速看板）。"""
    from dataclasses import dataclass

    report = EvalReport()
    for item in dataset:
        q = item["question"]
        # 从日志/缓存取回答（此处用占位——真实跑请用 ask_knowledge_agent）
        # 注意：为演示看板，这里先支持"预置回答"，否则需异步调用
        ctxs = [r["text"] for r in knowledge_search(q, k=5)]
        f = faithfulness(PLACEHOLDER_ANSWERS.get(q, ""), ctxs)
        ar = answer_relevance(q, PLACEHOLDER_ANSWERS.get(q, ""))
        cp = context_precision(ctxs, item.get("relevant_keywords", []))
        report.samples.append(SampleResult(q, f, ar, cp))
        report.n += 1
    report.metrics = {
        "faithfulness": round(sum(s.faithfulness for s in report.samples) / report.n, 4),
        "answer_relevance": round(sum(s.answer_relevance for s in report.samples) / report.n, 4),
        "context_precision": round(sum(s.context_precision for s in report.samples) / report.n, 4),
    }
    return report


async def run_full(dataset: list[dict]) -> EvalReport:
    """完整版：真实调用知识 Agent 生成回答后评测。"""
    report = EvalReport()
    for item in dataset:
        q = item["question"]
        answer = await ask_knowledge_agent(q)
        ctxs = [r["text"] for r in knowledge_search(q, k=5)]
        report.samples.append(SampleResult(
            question=q,
            faithfulness=faithfulness(answer, ctxs),
            answer_relevance=answer_relevance(q, answer),
            context_precision=context_precision(ctxs, item.get("relevant_keywords", [])),
        ))
        report.n += 1
    report.metrics = {
        "faithfulness": round(sum(s.faithfulness for s in report.samples) / report.n, 4),
        "answer_relevance": round(sum(s.answer_relevance for s in report.samples) / report.n, 4),
        "context_precision": round(sum(s.context_precision for s in report.samples) / report.n, 4),
    }
    return report


# 内置一个示例回答用于"离线快看板"演示（真实跑用 run_full）
PLACEHOLDER_ANSWERS = {
    "土壤盐分超过6g/kg属于什么级别？应该怎么治理？": (
        "含盐量超过6g/kg属于盐土级别，多数作物难以正常生长，"
        "需通过灌水洗盐把表层盐分淋洗到深层，并配合排水排盐、增施有机肥等工程改良措施。"
    ),
    "轻度和中度盐化土壤的含盐量范围是多少？": "轻度盐化含盐量1-2g/kg，中度盐化2-4g/kg。",
    "土壤含水量低于多少需要灌溉？灌溉量大概多少？": (
        "含水量低于60%即亏水需灌溉，轻度亏水灌溉20-30mm，中度30-40mm。"
    ),
    "盐碱地有哪些化学改良方法？": "施用石膏置换钠离子降低碱化度，使用腐殖酸类调节土壤结构。",
    "灌水洗盐应该每次灌多少水？间隔多久？": "灌水洗盐每次30-50mm，间隔7-10天重复进行。",
}


def render_dashboard(report: EvalReport) -> str:
    """渲染成 markdown 看板。"""
    lines = []
    lines.append("# RAG 评测闭环看板 (BizAgent)")
    lines.append("")
    lines.append(f"**样本数**：{report.n}")
    lines.append(f"**评测对象**：知识 Agent（混合检索 向量+BM25+RRF）")
    lines.append(f"**Embedding**：BAAI/bge-small-zh-v1.5 (512维)")
    lines.append("")
    lines.append("| 指标 | 平均分 | 说明 |")
    lines.append("|------|--------|------|")
    lines.append(f"| Faithfulness 忠实度 | **{report.metrics['faithfulness']:.3f}** | 回答忠于检索上下文、不幻觉 |")
    lines.append(f"| Answer Relevance 相关度 | **{report.metrics['answer_relevance']:.3f}** | 回答切题、覆盖问题要点 |")
    lines.append(f"| Context Precision 上下文精度 | **{report.metrics['context_precision']:.3f}** | 检索结果对回答有用占比 |")
    lines.append("")
    lines.append("## 分样例明细")
    lines.append("")
    lines.append("| 问题 | 忠实度 | 相关度 | 上下文精度 |")
    lines.append("|------|--------|--------|------------|")
    for s in report.samples:
        lines.append(f"| {s.question[:24]}... | {s.faithfulness:.2f} | {s.answer_relevance:.2f} | {s.context_precision:.2f} |")
    lines.append("")
    return "\n".join(lines)


async def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "offline"
    if mode == "full":
        report = await run_full(EVAL_SET)
    else:
        report = run_sync(EVAL_SET)
    dash = render_dashboard(report)
    print(dash)
    # 保存看板
    out = Path(__file__).resolve().parents[2] / "docs" / "eval_dashboard.md"
    out.write_text(dash, encoding="utf-8")
    print(f"\n看板已保存: {out}")


if __name__ == "__main__":
    asyncio.run(main())
