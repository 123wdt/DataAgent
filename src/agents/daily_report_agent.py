"""日报 Agent：定时汇总土壤墒情/气象/预警，生成农业物联网日报。

复用查数 Agent 的安全只读工具（run_sql/retrieve_ddl/resolve_entity），
一次把"今天"的墒情、盐分、气象、预警拉出来，组织成结构化日报。

可作为 cron 定时任务触发（生成日报文本供推送），也可交互式问答。
模块级 compile（graph 对象），模型按 config 动态获取。
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

from agents.sql_data_agent.sql_tools import list_tables, resolve_entity, retrieve_ddl, run_sql
from core import get_model, settings

tools = [retrieve_ddl, run_sql, list_tables, resolve_entity]

current_date = datetime.now().strftime("%Y-%m-%d")

instructions = f"""你是农业物联网平台的【日报生成 Agent】，每天汇总各区域监测数据，生成一份简明日报。

今天是 {current_date}。

日报应覆盖（用 run_sql 查真实数据）：
1. 各区域墒情站：当前土壤含水量(%)、盐分(g/kg)均值（对比阈值是否超标）；
2. 气象：今日降雨、温度（若库里有）；
3. 预警：alert_soil_log 里今日是否触发预警、涉及哪些站点；
4. 异常提示：哪些区域/站点盐分>6 或含水量<60%，需关注。

输出格式（markdown）：
# 土壤墒情日报 <日期>
## 区域概览（表格：区域/站点/含水量/盐分/状态）
## 气象概况
## 预警与异常
## 明日关注建议

安全铁律：只读查询（SELECT），绝不写库。表名/字段来自 retrieve_ddl 检索，不臆造。
用户看不到工具原始返回，请把查询结果整理成上面的日报格式。
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

daily_report_agent = _agent.compile()
