"""对 Agent 做语义缓存包装：相同/相似问题直接复用缓存回答，跳过 LLM 调用。

用法：
    cached_ask = wrap_agent(agent, get_answer=ask_fn)
    answer = await cached_ask(question)   # 命中缓存则零 LLM 调用
"""

from __future__ import annotations

import asyncio
from typing import Awaitable, Callable

from cache.semantic_cache import get_cache


def wrap_agent(
    agent,
    ask_fn: Callable[[str], Awaitable[str]],
    cache=None,
    hit_log: list | None = None,
) -> Callable[[str], Awaitable[str]]:
    """返回一个带语义缓存的异步 ask 函数。

    agent:  仅用于标识（可选）
    ask_fn: 真正调用 agent 得到回答的异步函数：async def ask(question) -> str
    hit_log: 可选，每次命中会 append 一条记录，便于统计命中率
    """
    cache = cache or get_cache()

    async def cached_ask(question: str) -> str:
        hit = cache.lookup(question)
        if hit is not None:
            if hit_log is not None:
                hit_log.append({"question": question, "hit": True})
            return hit
        answer = await ask_fn(question)
        cache.store(question, answer)
        if hit_log is not None:
            hit_log.append({"question": question, "hit": False})
        return answer

    return cached_ask
