"""知识 Agent 的工具集。

- KnowledgeSearch: 混合检索农业知识库（向量+BM25+RRF），返回带编号的 chunk。
"""

from __future__ import annotations

from typing import Annotated

from langchain_core.tools import tool


@tool
def knowledge_search(
    query: Annotated[str, "用中文描述要查的农业知识问题，如'土壤盐分超标的治理方法'"],
    k: Annotated[int, "返回的文档块数量"] = 5,
) -> str:
    """从农业物联网知识库做混合检索（语义+关键词双路融合），返回最相关的知识片段。

    用于查询土壤墒情、盐碱地治理、灌溉决策、施肥管理、预警诊断方法等农业领域知识。
    """
    from agents.knowledge_agent.kb import knowledge_search

    results = knowledge_search(query, k=k)
    if not results:
        return "未检索到相关知识片段。"
    lines = []
    for r in results:
        lines.append(f"[{r['id']}] (score={r['score']})\n{r['text']}")
    return "\n\n".join(lines)


@tool
def list_knowledge_sources() -> str:
    """列出知识库覆盖的主题，便于确认可回答的范围。"""
    from agents.knowledge_agent.kb import load_chunks

    chunks = load_chunks()
    titles = []
    seen = set()
    for c in chunks:
        first = c.splitlines()[0].strip() if c.splitlines() else ""
        if first and first.startswith("#") and first not in seen:
            seen.add(first)
            titles.append(first)
    return "\n".join(titles[:30]) or "暂无知识条目"
