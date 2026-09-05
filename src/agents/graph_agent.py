"""GraphRAG Agent：通过自实现知识图谱（三元组+社区+子图检索）回答农业领域关系型问题。

区别于向量 RAG：向量回答"语义相似"，图回答"结构关系"（盐碱地->哪些治理方法）。
可作为独立 agent 注册，也可作为 knowledge-agent 的补充检索路径。
"""

from __future__ import annotations

from typing import Literal

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, SystemMessage
from langchain_core.runnables import RunnableConfig, RunnableLambda, RunnableSerializable
from langgraph.graph import END, MessagesState, StateGraph
from langgraph.managed import RemainingSteps
from langgraph.prebuilt import ToolNode
from langchain_core.tools import tool

from core import get_model, settings


@tool
def graph_retrieve(query: str, radius: int = 2) -> str:
    """在农业知识图谱中检索与 query 相关的实体子图与社区上下文（结构化关系）。

    用于回答"X 有哪些方法/措施/关联"这类关系型问题。
    """
    from graph import get_kg, retrieve_subgraph
    r = retrieve_subgraph(get_kg(), query, radius=radius)
    if not r["context"]:
        return "知识图谱中未找到与查询相关的实体。"
    return r["context"]


tools = [graph_retrieve]

instructions = """你是【GraphRAG 图检索 Agent】，使用农业知识图谱（实体关系图）回答关系型问题。

当用户问"某事物有哪些方法/措施/关联/如何处理"这类问题，用 graph_retrieve 检索
实体关系子图，然后基于返回的【局部实体关系子图】和【全局社区上下文】组织回答。

示例问题：盐碱地怎么治理 / 灌溉决策的依据 / 盐碱地能种什么作物。
回答要点：列出相关实体及其关系，结构清晰。
如果图谱没有相关内容，如实说明，不编造。
"""


class AgentState(MessagesState, total=False):
    remaining_steps: RemainingSteps


def wrap_model(model: BaseChatModel) -> RunnableSerializable[AgentState, AIMessage]:
    bound = model.bind_tools(tools)
    pre = RunnableLambda(lambda s: [SystemMessage(content=instructions)] + s["messages"])
    return pre | bound


async def acall_model(state: AgentState, config: RunnableConfig) -> AgentState:
    m = get_model(config["configurable"].get("model", settings.DEFAULT_MODEL))
    resp = await wrap_model(m).ainvoke(state, config)
    if state["remaining_steps"] < 2 and resp.tool_calls:
        return {"messages": [AIMessage(id=resp.id, content="需要更多步骤，请换个问法。")]}
    return {"messages": [resp]}


def pending_tool_calls(state: AgentState) -> Literal["tools", "done"]:
    last = state["messages"][-1]
    if isinstance(last, AIMessage) and last.tool_calls:
        return "tools"
    return "done"


_g = StateGraph(AgentState)
_g.add_node("model", acall_model)
_g.add_node("tools", ToolNode(tools))
_g.set_entry_point("model")
_g.add_edge("tools", "model")
_g.add_conditional_edges("model", pending_tool_calls, {"tools": "tools", "done": END})
graph_agent = _g.compile()
