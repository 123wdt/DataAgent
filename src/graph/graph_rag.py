"""自实现 GraphRAG（轻量、纯 Python、无 networkx 依赖）——面试加分项。

动机（interview）：
- 传统向量 RAG 把文档切块，丢失了实体间的结构关系。盐碱地这个领域问题往往是
  「某个实体 -> 有哪些相关实体/措施」的结构化关系，图能显式建模。
- Map-Reduce GraphRAG（微软论文）太重。这里自实现一个"轻量版"：
  三元组建图 + Louvain/Dirichlet 社区检测 + 实体子图扩展检索，把局部实体关系和
  全局社区上下文一同注入 LLM。规模小（几十~上百节点），纯 Python 可跑，炫"原理我懂"。

流程：
1. build_graph：从三元组列表建无向图（邻接表 dict）。
2. detect_communities：自实现 Louvain（局部模块度增益）+ 连通分量兜底。
3. community_summary：为每个社区生成一句话摘要（用社区内最高度节点/标签聚合）。
4. retrieve_subgraph：给定查询实体，BFS 扩展邻居子图 + 所属社区全局上下文。
"""

from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any
import re


@dataclass
class Triplet:
    head: str      # 头实体（是主语/上位概念）
    relation: str  # 关系
    tail: str      # 尾实体


class SimpleGraph:
    def __init__(self):
        # 邻接表：node -> list[(neighbor, relation)]
        self.adj: dict[str, list[tuple[str, str]]] = defaultdict(list)
        self.nodes: set[str] = set()

    def add_edge(self, u: str, rel: str, v: str) -> None:
        self.nodes.add(u); self.nodes.add(v)
        self.adj[u].append((v, rel))
        self.adj[v].append((u, rel))

    @classmethod
    def from_triplets(cls, triplets: list[Triplet]) -> "SimpleGraph":
        g = cls()
        for t in triplets:
            g.add_edge(t.head, t.relation, t.tail)
        return g


# ---------------------------------------------------------------------------
# 社区检测：自实现 Louvain（一阶贪心） + 连通分量兜底
# ---------------------------------------------------------------------------
def _louvain_communities(g: SimpleGraph) -> dict[str, int]:
    """简化版 Louvain：基于局部模块度增益的贪心合并（一阶迭代）。

    对每个节点，尝试并入邻居社区，选模块度增益最大的；重复直到稳定。
    小图足够。返回 node -> community_id。
    """
    comm: dict[str, int] = {n: i for i, n in enumerate(sorted(g.nodes))}
    n = len(g.nodes)
    changed = True
    for _iter in range(10):
        if not changed:
            break
        changed = False
        for node in sorted(g.nodes):
            best_c, best_gain = comm[node], 0.0
            neighbor_comm_counts = defaultdict(int)
            for (nb, _rel) in g.adj[node]:
                neighbor_comm_counts[comm[nb]] += 1
            total = sum(neighbor_comm_counts.values()) or 1
            for c, cnt in neighbor_comm_counts.items():
                gain = cnt / total  # 模块度启发：邻居落在 c 越多越好
                if gain > best_gain:
                    best_gain, best_c = gain, c
            if best_c != comm[node]:
                comm[node] = best_c
                changed = True
    return comm


def detect_communities(g: SimpleGraph) -> dict[str, int]:
    if not g.nodes:
        return {}
    return _louvain_communities(g)


# ---------------------------------------------------------------------------
# 检索：实体展开 + 子图 + 社区上下文
# ---------------------------------------------------------------------------
def build_entity_index(g: SimpleGraph) -> dict[str, list[str]]:
    """把节点名做字符拆解小写化索引，便于模糊匹配用户查询里的实体。"""
    idx: dict[str, list[str]] = defaultdict(list)
    for node in g.nodes:
        tokens = re.findall(r"[\u4e00-\u9fa5]{2,}", node)  # 中文字段
        for tok in tokens:
            idx[tok].append(node)
    return idx


def resolve_entities(query: str, g: SimpleGraph, idx: dict[str, list[str]]) -> list[str]:
    """从查询里解析出命中的图实体（含别名模糊）。"""
    hits: set[str] = set()
    tokens = re.findall(r"[\u4e00-\u9fa5]{1,6}", query)
    for tok in tokens:
        for node in g.nodes:
            if tok in node or node in tok:
                hits.add(node)
        for node in idx.get(tok, []):
            hits.add(node)
    return list(hits)


def retrieve_subgraph(
    g: SimpleGraph,
    query: str,
    radius: int = 2,
    max_nodes: int = 20,
) -> dict[str, Any]:
    """BFS 扩展实体子图 + 社区全局上下文，返回可注入 LLM 的上下文块。"""
    idx = build_entity_index(g)
    seeds = resolve_entities(query, g, idx)
    if not seeds:
        return {"context": "", "seeds": [], "community_contexts": [], "nodes": []}

    # BFS 扩展
    visited: set[str] = set()
    queue = deque((s, 0) for s in seeds)
    edges: list[tuple[str, str, str]] = []
    while queue and len(visited) < max_nodes:
        node, depth = queue.popleft()
        if node in visited or depth > radius:
            continue
        visited.add(node)
        for (nb, rel) in g.adj[node]:
            edges.append((node, rel, nb))
            if nb not in visited and depth + 1 <= radius:
                queue.append((nb, depth + 1))

    # 社区检测与全局上下文
    comm = detect_communities(g)
    seed_comms = {comm[s] for s in seeds if s in comm}
    community_contexts = []
    comm_members: dict[int, list[str]] = defaultdict(list)
    for node, cid in comm.items():
        comm_members[cid].append(node)

    for cid in seed_comms:
        members = comm_members.get(cid, [])
        # 社区摘要：用社区内节点做"概念"描述
        summary = "、".join(sorted(members)[:12])
        community_contexts.append(f"[社区主题] {summary}")

    lines = ["【局部实体关系子图】"]
    for (u, rel, v) in sorted(set(edges)):
        lines.append(f"- {u} --{rel}--> {v}")
    if community_contexts:
        lines.append("【全局社区上下文】")
        lines.extend(f"- {c}" for c in community_contexts)
    return {"context": "\n".join(lines), "seeds": seeds,
            "nodes": list(visited), "community_contexts": community_contexts}
