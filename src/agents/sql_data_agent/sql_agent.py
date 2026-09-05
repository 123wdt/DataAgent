"""查数 Agent（NL2SQL）：基于 ReAct 编排的数据库问答代理。

流程（双代理设计，差异化点）：
  1. 先 RAG-on-DDL 检索（RetrieveDDL）—— 根据问题语义找到要用的表
  2. LLM 基于命中的 DDL 卡片生成只读 SQL
  3. RunSQL 执行（安全三层拦截写操作/越权表/超限）
  4. 把结果与卡片回填，LLM 组织成自然语言回答（含来源表）

多轮对话：基于 MessagesState 天然支持，历史消息参与生成。
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

from agents.sql_data_agent.chart import generate_chart
from agents.sql_data_agent.sql_tools import (
    list_tables,
    resolve_entity,
    retrieve_ddl,
    run_sql,
)
from core import get_model, settings

tools = [retrieve_ddl, run_sql, list_tables, resolve_entity, generate_chart]

current_date = datetime.now().strftime("%Y-%m-%d")

instructions = f"""你是农业物联网"查数 Agent"，负责根据用户的问题查询业务数据库并给出简明回答。

今天是 {current_date}。业务库含：区域(region_zone)→地块(region_patch)→站点(mon_station)→监测记录
(mon_soil_record 土壤墒情:含水/盐分; mon_weather_record 气象; mon_groundwater_record 地下水; mon_ph_record pH)，
以及预警(alert_soil_log / alert_threshold)、灌溉(irri_control / irri_fertilizer_tank)。

回答问题的步骤（务必按此顺序）：
1. 先用 resolve_entity 解析问题里的时间/地点/站点/指标，得到结构化条件。
2. 用 retrieve_ddl 检索"用哪张表"及字段/单位/外键（RAG-on-DDL，别猜表名）。
3. 用 run_sql 执行只读 SQL（只写 SELECT，JOIN 时用外键关联，时间按解析出的条件过滤）。
4. 若一次没查对，根据报错调整 SQL 重试，最多 2~3 次。

约束：
- 只读！绝不允许 INSERT/UPDATE/DELETE/DROP 等任何写操作。
- 表名、字段名必须来自 DDL 卡片，不要臆造。
- 回答用中文，数据要量化（给出数字和单位），必要时用 markdown 表格展示。
- 当查询结果是趋势(按时间)或对比(多站点/多区域)数据时，用 generate_chart 生成 ECharts
  图表配置，并把图表 JSON 以 ```chart 代码块形式附在回答末尾，方便前端渲染。
  折线图用于时间趋势，柱状图用于对比，饼图用于占比。

注意：用户看不到工具返回的原始结果，请把查询结果整理成自然语言或表格后再回答。
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
agent = StateGraph(AgentState)
agent.add_node("model", acall_model)
agent.add_node("tools", ToolNode(tools))
agent.set_entry_point("model")
agent.add_edge("tools", "model")


def pending_tool_calls(state: AgentState) -> Literal["tools", "done"]:
    last = state["messages"][-1]
    if isinstance(last, AIMessage) and last.tool_calls:
        return "tools"
    return "done"


agent.add_conditional_edges("model", pending_tool_calls, {"tools": "tools", "done": END})

sql_data_agent = agent.compile()
