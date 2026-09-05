from dataclasses import dataclass

from langgraph.graph.state import CompiledStateGraph
from langgraph.pregel import Pregel

from agents.bg_task_agent.bg_task_agent import bg_task_agent
from agents.chatbot import chatbot
from agents.command_agent import command_agent
from agents.daily_report_agent import daily_report_agent
from agents.github_mcp_agent.github_mcp_agent import github_mcp_agent
from agents.graph_agent import graph_agent
from agents.interrupt_agent import interrupt_agent
from agents.knowledge_agent import diagnosis_agent, knowledge_agent
from agents.knowledge_base_agent import kb_agent
from agents.langgraph_supervisor_agent import langgraph_supervisor_agent
from agents.langgraph_supervisor_hierarchy_agent import langgraph_supervisor_hierarchy_agent
from agents.lazy_agent import LazyLoadingAgent
from agents.rag_assistant import rag_assistant
from agents.research_assistant import research_assistant
from agents.sql_data_agent import sql_data_agent
from schema import AgentInfo

DEFAULT_AGENT = "research-assistant"

# Type alias to handle LangGraph's different agent patterns
# - @entrypoint functions return Pregel
# - StateGraph().compile() returns CompiledStateGraph
AgentGraph = CompiledStateGraph | Pregel  # What get_agent() returns (always loaded)
AgentGraphLike = CompiledStateGraph | Pregel | LazyLoadingAgent  # What can be stored in registry


@dataclass
class Agent:
    description: str
    graph_like: AgentGraphLike


agents: dict[str, Agent] = {
    "chatbot": Agent(description="A simple chatbot.", graph_like=chatbot),
    "research-assistant": Agent(
        description="A research assistant with web search and calculator.",
        graph_like=research_assistant,
    ),
    "rag-assistant": Agent(
        description="A RAG assistant with access to information in a database.",
        graph_like=rag_assistant,
    ),
    "command-agent": Agent(description="A command agent.", graph_like=command_agent),
    "bg-task-agent": Agent(description="A background task agent.", graph_like=bg_task_agent),
    "langgraph-supervisor-agent": Agent(
        description="A langgraph supervisor agent", graph_like=langgraph_supervisor_agent
    ),
    "langgraph-supervisor-hierarchy-agent": Agent(
        description="A langgraph supervisor agent with a nested hierarchy of agents",
        graph_like=langgraph_supervisor_hierarchy_agent,
    ),
    "interrupt-agent": Agent(
        description="An agent the uses interrupts.", graph_like=interrupt_agent
    ),
    "knowledge-base-agent": Agent(
        description="A retrieval-augmented generation agent using Amazon Bedrock Knowledge Base",
        graph_like=kb_agent,
    ),
    "github-mcp-agent": Agent(
        description="A GitHub agent with MCP tools for repository management and development workflows.",
        graph_like=github_mcp_agent,
    ),
    "sql-data-agent": Agent(
        description="农业物联网查数Agent：自然语言查业务库(NL2SQL+RAG-on-DDL+只读安全)，返回数据与图表。",
        graph_like=sql_data_agent,
    ),
    "knowledge-agent": Agent(
        description="农业物联网知识Agent：混合检索(向量+BM25+RRF)问答，带出处溯源。",
        graph_like=knowledge_agent,
    ),
    "diagnosis-agent": Agent(
        description="预警诊断Agent：数据证明+建议出处双轨，输出土壤墒情/盐碱异常诊断报告。",
        graph_like=diagnosis_agent,
    ),
    "daily-report-agent": Agent(
        description="日报Agent：汇总各区域墒情/气象/预警，生成农业物联网日报。",
        graph_like=daily_report_agent,
    ),
    "graph-agent": Agent(
        description="GraphRAG图检索Agent：通过自实现农业知识图谱(三元组+社区+子图)回答关系型问题。",
        graph_like=graph_agent,
    ),
}


async def load_agent(agent_id: str) -> None:
    """Load lazy agents if needed."""
    graph_like = agents[agent_id].graph_like
    if isinstance(graph_like, LazyLoadingAgent):
        await graph_like.load()


def get_agent(agent_id: str) -> AgentGraph:
    """Get an agent graph, loading lazy agents if needed."""
    agent_graph = agents[agent_id].graph_like

    # If it's a lazy loading agent, ensure it's loaded and return its graph
    if isinstance(agent_graph, LazyLoadingAgent):
        if not agent_graph._loaded:
            raise RuntimeError(f"Agent {agent_id} not loaded. Call load() first.")
        return agent_graph.get_graph()

    # Otherwise return the graph directly
    return agent_graph


def get_all_agent_info() -> list[AgentInfo]:
    return [
        AgentInfo(key=agent_id, description=agent.description) for agent_id, agent in agents.items()
    ]
