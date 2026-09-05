"""轻量语义缓存：对语义相似问题复用回答，省 LLM 调用。"""

from cache.semantic_cache import SemanticCache, get_cache

__all__ = ["SemanticCache", "get_cache"]
