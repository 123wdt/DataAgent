"""W2 端到端测试：知识Agent混合检索 + 诊断Agent双轨制。"""
import sys, asyncio
sys.path.insert(0, "src")
from langgraph.checkpoint.memory import InMemorySaver
from langchain_core.messages import HumanMessage
from agents.knowledge_agent import knowledge_agent, diagnosis_agent
from core import get_model

async def run(agent, question, name):
    print(f"\n{'='*60}\n[{name}] Q: {question}\n{'='*60}")
    config = {"configurable": {"thread_id": "w2test"}, "recursion_limit": 40}
    from core import settings
    m = get_model(settings.DEFAULT_MODEL)
    # 直接走 graph 编译产物，配 checkpointer
    final = await agent.ainvoke(
        {"messages": [HumanMessage(content=question)]},
        config={"configurable": {"model": settings.DEFAULT_MODEL}, "recursion_limit": 40},
    )
    # 打印最后一条AI消息
    for msg in reversed(final["messages"]):
        if hasattr(msg, "content") and getattr(msg, "content", None) and not getattr(msg, "tool_calls", None):
            print("\n--- 回答 ---\n", msg.content)
            return

async def main():
    # 1) 知识混合检索问答
    await run(knowledge_agent, "土壤盐分超标应该怎么治理？请给出具体措施和阈值标准。", "knowledge-agent")
    # 2) 诊断Agent双轨制
    await run(diagnosis_agent, "南区墒情站最近土壤盐分是不是超标了？如果是，该怎么处理？", "diagnosis-agent")

asyncio.run(main())
