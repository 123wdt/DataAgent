"""知识 Agent：农业物联网领域知识问答（向量+关键词双路混合检索 + RRF）。

回答强制带溯源引用 [n]，n 对应知识检索返回的文档块编号，保证"出处可查"（面试炫技点）。

采用模块级编译（graph 对象），模型在 node 内按 config 动态获取，与 sql_data_agent 一致。
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, SystemMessage
from langchain_core.runnables import RunnableConfig, RunnableLambda, RunnableSerializable
from langgraph.graph import END, MessagesState, StateGraph
from langgraph.managed import RemainingSteps
from langgraph.prebuilt import ToolNode

from agents.knowledge_agent.knowledge_tools import knowledge_search, list_knowledge_sources
from core import get_model, settings

tools = [knowledge_search, list_knowledge_sources]

current_date = datetime.now().strftime("%Y-%m-%d")

instructions = f"""你是农业物联网与土壤科学领域的【知识问答专家】，负责回答关于土壤墒情、盐碱地治理、\
灌溉决策、施肥管理、土壤改良、预警诊断流程等问题。

今天是 {current_date}。

规则：
- 只依据知识库（knowledge_search）检索到的内容回答，不要编造知识。
- 回答必须给出知识出处：在被引用的内容后标注 [n]，n 是 knowledge_search 返回的文档块编号。
- 如果检索不到相关内容，明确说"知识库暂无该主题"，不要猜测。
- 用中文回答，专业、条理清晰。涉及数值（含盐量 g/kg、灌溉 mm、含水量%）要准确。
- 若一次检索不够，换关键词再检索一次再回答。
- 用户看不到工具原始返回，请把知识组织成通顺的、带 [n] 引用的回答。

注意：引用只允许使用 knowledge_search 返回的块编号，不可编造出处。
"""


class AgentState(MessagesState, total=False):
    remaining_steps: RemainingSteps


def wrap_model(model: BaseChatModel) -> RunnableSerializable[AgentState, AIMessage]:
    bound_model = model.bind_tools(tools)
    preprocessor = RunnableLambda(
        lambda state: [SystemMessage(content=instructions)] + state["messages"],
        name="StateModifier",
    )
    return preprocessor | bound_model  # type: ignore[return-value]


async def acall_model(state: AgentState, config: RunnableConfig) -> AgentState:
    m = get_model(config["configurable"].get("model", settings.DEFAULT_MODEL))
    model_runnable = wrap_model(m)
    response = await model_runnable.ainvoke(state, config)
    if state["remaining_steps"] < 2 and response.tool_calls:
        return {"messages": [AIMessage(id=response.id, content="抱歉，需要更多步骤处理该请求，请换个问法。")]}
    return {"messages": [response]}


# ---- Graph ----
_agent = StateGraph(AgentState)
_agent.add_node("model", acall_model)
_agent.add_node("tools", ToolNode(tools))
_agent.set_entry_point("model")
_agent.add_edge("tools", "model")


def pending_tool_calls(state: AgentState) -> Literal["tools", "done"]:
    last = state["messages"][-1]
    if isinstance(last, AIMessage) and last.tool_calls:
        return "tools"
    return "done"


_agent.add_conditional_edges("model", pending_tool_calls, {"tools": "tools", "done": END})

knowledge_agent = _agent.compile()


# 兼容 builder 形式
def build_knowledge_agent(model: BaseChatModel = None) -> Any:
    return knowledge_agent
