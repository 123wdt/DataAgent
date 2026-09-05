"""增量索引：通过"源文件指纹"判断知识源是否变更，只在该变更时才重建向量索引。

取代"每次调用都全量重建"的低效做法（interview 亮点：增量更新省 embedding 计算）。

原理：
- 为每个索引记录它依赖的源文件清单及其内容哈希（MD5）。
- ensure_* 时对比当前源文件的哈希与上次记录的指纹：
    - 一致 -> 索引仍有效，直接复用（零重建）
    - 变化 -> 触发重建，并更新指纹
- 指纹持久化到 vector_store/*.fingerprint.json，重启不丢。
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from agents.sql_data_agent.embeddings import (
    PROJECT_ROOT,
    SCHEMA_PATH,
    DEFAULT_PERSIST as RAG_DDL_PERSIST,
)

# 知识库目录（knowledge/*.md）
KNOWLEDGE_DIR = PROJECT_ROOT / "knowledge"

FINGERPRINT_DIR = PROJECT_ROOT / "vector_store"


def _md5(text: str) -> str:
    return hashlib.md5(text.encode("utf-8")).hexdigest()


def _schema_fingerprint() -> dict:
    return {"schema.sql": _md5(SCHEMA_PATH.read_text(encoding="utf-8"))}


def _knowledge_fingerprint() -> dict:
    fp = {}
    for md in sorted(KNOWLEDGE_DIR.glob("*.md")):
        fp[md.name] = _md5(md.read_text(encoding="utf-8"))
    return fp


def _load(fp_path: Path) -> dict:
    if fp_path.exists():
        try:
            return json.loads(fp_path.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            return {}
    return {}


def _save(fp_path: Path, data: dict) -> None:
    FINGERPRINT_DIR.mkdir(parents=True, exist_ok=True)
    fp_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def schema_changed() -> bool:
    """RAG-on-DDL 索引的源（schema.sql）是否变了。"""
    fp_path = FINGERPRINT_DIR / "rag_ddl.fingerprint.json"
    cur = _schema_fingerprint()
    old = _load(fp_path)
    return old != cur


def mark_schema_built() -> None:
    fp_path = FINGERPRINT_DIR / "rag_ddl.fingerprint.json"
    _save(fp_path, _schema_fingerprint())


def knowledge_changed() -> bool:
    """知识 Agent 词库（knowledge/*.md）是否变了。注意：索引内存态，按进程重建。"""
    fp_path = FINGERPRINT_DIR / "knowledge.fingerprint.json"
    cur = _knowledge_fingerprint()
    old = _load(fp_path)
    return old != cur


def mark_knowledge_built() -> None:
    fp_path = FINGERPRINT_DIR / "knowledge.fingerprint.json"
    _save(fp_path, _knowledge_fingerprint())


def ensure_rag_ddl_index() -> bool:
    """确保 RAG-on-DDL 索引是最新的；变更则重建，返回是否重建。"""
    from agents.sql_data_agent.embeddings import build_index_from_schema, load_index

    if schema_changed() or load_index() is None:
        build_index_from_schema()
        mark_schema_built()
        return True
    return False
