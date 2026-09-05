"""Embedding 抽象与向量检索（RAG-on-DDL 的检索底座）。

embedding 采用 fastembed（基于 onnxruntime，纯本地、无 torch 依赖），
模型 = BAAI/bge-small-zh-v1.5（中文语义向量，512 维），从 hf-mirror 下载。

retriever 接口：
  - build_index(cards, persist_dir)   把 DDL 卡片向量化写入 Chroma
  - search(query, k)                  语义检索最相关的 DDL 卡片文本
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")

from langchain_chroma import Chroma  # noqa: E402
from langchain_core.documents import Document  # noqa: E402

from agents.sql_data_agent.ddl import TableCard  # noqa: E402

logger = logging.getLogger(__name__)

# 项目根目录 = <root>/src/agents/sql_data_agent 的第3级 parent
PROJECT_ROOT = Path(__file__).resolve().parents[3]

EMBED_MODEL = "BAAI/bge-small-zh-v1.5"
DEFAULT_PERSIST = str(PROJECT_ROOT / "vector_store" / "rag_ddl")
SCHEMA_PATH = PROJECT_ROOT / "scripts" / "db" / "schema.sql"
MODELS_CACHE = str(PROJECT_ROOT / "models" / "embed")
COLLECTION = "bizagent_rag_ddl"
_embed_fn: Any = None
# 进程内 Chroma 实例缓存：persist_dir -> Chroma（避免重复创建 PersistentClient）
_CHROMA_CACHE: dict[str, Any] = {}


def get_embedding_function() -> Any:
    """返回一个带 __call__ 的 embedding 函数（供 langchain Chroma + fastembed 使用）。"""
    global _embed_fn
    if _embed_fn is None:
        from fastembed import TextEmbedding

        model = TextEmbedding(EMBED_MODEL, cache_dir=MODELS_CACHE)

        class FastEmbedEmbeddings:
            def __init__(self, m):
                self._m = m

            def embed_query(self, text: str) -> list[float]:
                return list(self._m.embed([text]))[0].tolist()

            def embed_documents(self, texts: list[str]) -> list[list[float]]:
                return [v.tolist() for v in self._m.embed(texts)]

        _embed_fn = FastEmbedEmbeddings(model)
    return _embed_fn


def _card_to_document(card: TableCard) -> Document:
    meta = {
        "table": card.table,
        "comment": card.comment,
        "pk": card.pk,
        "fk": ";".join(f"{k}->{v}" for k, v in card.fk.items()) or "",
    }
    return Document(page_content=card.text, metadata=meta)


def build_index(cards: list[TableCard], persist_dir: str = DEFAULT_PERSIST) -> Chroma:
    """把 DDL 卡片写入 Chroma 向量库（幂等：先删旧集合再建，保证可重建）。"""
    import shutil

    import chromadb

    # 重建 inform 目录，保证可重复执行
    if os.path.isdir(persist_dir):
        shutil.rmtree(persist_dir)
    os.makedirs(persist_dir, exist_ok=True)

    emb = get_embedding_function()
    docs = [_card_to_document(c) for c in cards if c.fields]

    db = Chroma.from_documents(
        documents=docs,
        embedding=emb,
        persist_directory=persist_dir,
        collection_name=COLLECTION,
    )
    logger.info("RAG-on-DDL index built: %d cards -> %s", len(docs), persist_dir)
    return db


def load_index(persist_dir: str = DEFAULT_PERSIST) -> Chroma | None:
    """加载已建好的向量库；不存在返回 None。

    进程内单例缓存同一个 persist_directory 的 Chroma 实例，避免每次工具调用
    都新建 PersistentClient（跨线程/重复创建可能触发 chromadb tenant 校验问题，
    也省去重复打开 sqlite 的开销）。
    """
    if not os.path.isdir(persist_dir):
        return None
    key = persist_dir
    if key not in _CHROMA_CACHE:
        emb = get_embedding_function()
        _CHROMA_CACHE[key] = Chroma(
            persist_directory=persist_dir,
            embedding_function=emb,
            collection_name=COLLECTION,
        )
    return _CHROMA_CACHE[key]


def search(query: str, k: int = 4, persist_dir: str = DEFAULT_PERSIST) -> list[str]:
    """语义检索命中的 DDL 卡片文本列表。"""
    db = load_index(persist_dir)
    if db is None:
        build_index_from_schema(persist_dir)
        db = load_index(persist_dir)
        if db is None:
            return []
    docs = db.similarity_search(query, k=k)
    return [d.page_content for d in docs]


def build_index_from_schema(persist_dir: str = DEFAULT_PERSIST) -> None:
    """从 scripts/db/schema.sql 直接构建索引（一体化，供工具/初始化调用）。"""
    from agents.sql_data_agent.ddl import parse_create_tables

    ddl = SCHEMA_PATH.read_text(encoding="utf-8")
    cards = parse_create_tables(ddl)
    build_index(cards, persist_dir)
