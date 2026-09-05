"""知识库加载与混合检索器构建。

加载 knowledge/*.md 农业知识文档，按标题/段落切块，构建 HybridRetriever。
复用 sql_data_agent.embeddings 的 embedding 函数（同一个 bge-small-zh 模型，避免重复加载）。
"""

from __future__ import annotations

import logging
import re
from pathlib import Path

from agents.knowledge_agent.hybrid_retriever import HybridRetriever
from agents.sql_data_agent.embeddings import get_embedding_function, PROJECT_ROOT

logger = logging.getLogger(__name__)

KNOWLEDGE_DIR = PROJECT_ROOT / "knowledge"
_MAX_CHUNK = 400  # 每个 chunk 的最大字符数

_retriever: HybridRetriever | None = None


def load_chunks() -> list[str]:
    """读取 knowledge/*.md，按章节标题切块（保留标题作为上下文）。"""
    chunks: list[str] = []
    for md in sorted(KNOWLEDGE_DIR.glob("*.md")):
        text = md.read_text(encoding="utf-8")
        # 按标题行切块
        parts = re.split(r"(?m)^(?=#{1,4} )", text)
        for part in parts:
            part = part.strip()
            if not part:
                continue
            # 块太长则按段落再切
            if len(part) <= _MAX_CHUNK:
                chunks.append(part)
            else:
                # 按空行分段，每个片段带标题前缀
                title = part.splitlines()[0][:30] if part.splitlines() else ""
                paras = [p.strip() for p in re.split(r"\n\s*\n", part) if p.strip()]
                acc = title
                for para in paras:
                    if len(acc) + len(para) > _MAX_CHUNK and len(acc) > len(title):
                        chunks.append(acc)
                        acc = title + "\n"
                    acc = acc + "\n" + para
                if acc.strip():
                    chunks.append(acc)
    return chunks


def get_retriever() -> HybridRetriever:
    """懒加载全局混合检索器（复用 embedding 模型）。"""
    global _retriever
    if _retriever is None:
        chunks = load_chunks()
        # 复用 sql_data_agent 的 embedding 函数（返回带 embed_documents/embed_query 的对象）
        class _Adapter:
            def __call__(self, texts: list[str]) -> list[list[float]]:
                return get_embedding_function().embed_documents(texts)

        _retriever = HybridRetriever(chunks, _Adapter())
        logger.info("知识库加载: %d 个chunk, %d 篇文档", len(chunks), len(list(KNOWLEDGE_DIR.glob("*.md"))))
    return _retriever


def knowledge_search(query: str, k: int = 5) -> list[dict]:
    """对外接口：混合检索知识库，返回 top-k chunk。"""
    return get_retriever().hybrid_search(query, k=k)
