"""W1 查数 Agent 端到端测试：直接 invoke LangGraph agent。"""
import sys
sys.path.insert(0, "src")
import asyncio
from agents.sql_data_agent import sql_data_agent

async def ask(question: str):
    print(f"\n{'='*60}\nQ: {question}")
    try:
        result = await sql_data_agent.ainvoke(
            {"messages": [{"role": "user", "content": question}]},
            {"configurable": {"checkpoint_id": None}},
        )
        for m in result["messages"]:
            role = "assistant" if m.type == "ai" else ("tool" if m.type == "tool" else m.type)
            if role == "tool":
                content = (m.content or "")[:200]
                print(f"  [tool] {content}")
            elif role == "assistant":
                print(f"  [AI] {m.content[:500]}")
    except Exception as e:
        print(f"  [错误] {type(e).__name__}: {e}")

async def main():
    for q in [
        "北区3号墒情站近7天平均含水量是多少",
        "哪个地块土壤盐分超标了",
        "最近的气象降雨情况如何",
    ]:
        await ask(q)

if __name__ == "__main__":
    asyncio.run(main())
