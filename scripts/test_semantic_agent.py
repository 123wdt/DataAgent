"""语义缓存集成测试：第一次真调知识Agent，同义第二次命中缓存。"""
import sys, asyncio
sys.path.insert(0, "src")
from langchain_core.messages import HumanMessage
from agents.knowledge_agent import knowledge_agent
from cache.cached_agent import wrap_agent
from core import settings

hit_log = []

async def ask_fn(q):
    resp = await knowledge_agent.ainvoke(
        {"messages": [HumanMessage(content=q)]},
        config={"configurable": {"model": settings.DEFAULT_MODEL}, "recursion_limit": 30})
    for m in reversed(resp["messages"]):
        if getattr(m, "content", None) and not getattr(m, "tool_calls", None):
            return m.content
    return ""

async def main():
    cached = wrap_agent(knowledge_agent, ask_fn, hit_log=hit_log)
    q1 = "土壤盐分超标应该怎么治理？"
    a1 = await cached(q1)
    hits_after_first = sum(1 for h in hit_log if h["hit"])
    print(f"[第1次] 真调LLM, 命中数={hits_after_first}")
    print("  答案开头:", a1[:60])
    # 同义第二次
    q2 = "土壤盐分超标怎么处理？"
    a2 = await cached(q2)
    print(f"\n[第2次-同义] '{q2}' 命中: {len(hit_log)>0 and hit_log[-1]['hit']}")
    print(f"  缓存命中次数(累计): {sum(1 for h in hit_log if h['hit'])}")
    # 精确第三次
    a3 = await cached(q1)
    print(f"[第3次-精确] '{q1}' 命中: {len(hit_log)>0 and hit_log[-1]['hit']}")

asyncio.run(main())
