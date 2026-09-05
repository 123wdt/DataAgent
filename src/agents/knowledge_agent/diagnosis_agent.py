"""预警诊断 Agent：数据证明 + 建议出处 双轨。

设计（面试炫技点 B1）：
- 双轨制诊断：任何结论都必须同时具备
  【数据证明】run_sql 查真实监测数据 +【建议出处】knowledge_search 检索知识库给处置方法与 [n] 出处。
- 流程：实体解析(resolve_entity) -> 查表结构(retrieve_ddl) -> 拉真实数据(run_sql) ->
  检索处置知识(knowledge_search) -> 输出结构化诊断报告。
- 安全：复用 sql_data_agent 的 run_sql（只读三层保护），绝无写操作。

模块级 compile（graph 对象），模型在 node 内按 config 动态获取。
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

from agents.knowledge_agent.knowledge_tools import knowledge_search
from agents.sql_data_agent.sql_tools import resolve_entity, retrieve_ddl, run_sql
from core import get_model, settings

tools = [resolve_entity, retrieve_ddl, run_sql, knowledge_search]

current_date = datetime.now().strftime("%Y-%m-%d")

instructions = f"""你是农业物联网平台的【土壤墒情与盐碱诊断专家】，负责对监测数据做预警诊断并提出处置建议。

今天是 {current_date}。

严格执行"双轨制"诊断——每个结论都必须有：
1. 【数据证明】用 run_sql 查数据库里的真实监测数据（盐分/含水量/气象等），证明现象确实存在；
2. 【建议出处】用 knowledge_search 检索农业知识库，给出处置建议，并标注出处 [n]。

诊断流程（务必按此顺序）：
1. resolve_entity 解析用户话里的区域/站点/时间/指标；
2. retrieve_ddl 了解相关表结构（字段名、单位、阈值来源）；
3. run_sql 查真实数据（当前值 + 近 N 天趋势），找出超标项；
4. knowledge_search 查对应的治理/处置知识，得到带出处的建议；
5. 输出结构化诊断报告。

报告模板（markdown）：
### 诊断结论
<一句话结论>
### 现象与数据
<哪个区域/站点、哪项指标、当前值、阈值、超标多少；附近几天趋势要点>
### 原因分析
<可能的成因：降雨不足/灌溉不足/排水不畅/传感器异常等，需结合数据判断>
### 处置建议
<具体措施 + 知识出处[n]>
### 溯源
<本次用到的数据来源表 + 知识出处编号列表>

安全铁律：
- 只能查数（SELECT），绝不写库。
- 只依据检索到的真实数据和知识库内容回答；知识库没有的就说明"知识库暂无该主题"。
- 用户看不到工具原始返回，请组织成上面的报告格式输出。
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

diagnosis_agent = _agent.compile()
