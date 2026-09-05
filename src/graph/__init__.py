"""自实现 GraphRAG：农业领域知识图谱（三元组建图 + 社区检测 + 子图检索）。"""

from graph.graph_rag import (
    SimpleGraph,
    Triplet,
    build_entity_index,
    detect_communities,
    resolve_entities,
    retrieve_subgraph,
)
from graph.agri_triplets import TRIPLETS

_KG: SimpleGraph | None = None


def get_kg() -> SimpleGraph:
    global _KG
    if _KG is None:
        _KG = SimpleGraph.from_triplets(TRIPLETS)
    return _KG


__all__ = [
    "TRIPLETS",
    "SimpleGraph",
    "Triplet",
    "get_kg",
    "retrieve_subgraph",
    "detect_communities",
    "resolve_entities",
    "build_entity_index",
]
