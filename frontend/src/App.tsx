// 主界面：左侧 agent 选择 + 右侧聊天窗口（SSE 流式）
import { useCallback, useEffect, useRef, useState } from "react";
import { fetchAgents, streamAgent, AgentInfo, StreamEvent } from "./api";
import MessageContent, { ContentBlock } from "./components/MessageContent";
import "./App.css";

interface Msg {
  role: "user" | "assistant";
  blocks: ContentBlock[];
  streaming?: boolean;
}

// ============ Agent 中文元数据 ============
// 覆盖左侧菜单、聊天头部、使用说明弹窗的全部文案
const AGENT_META: Record<string, { name: string; desc: string; usage: string; examples: string[] }> = {
  // ---- 5 个业务 Agent ----
  "sql-data-agent": {
    name: "查数助手",
    desc: "自然语言查数：问含水量/盐分/气象，自动查数据库并出图表",
    usage: "直接问与土壤监测数据相关的问题，如某站点的含水量、盐分、气象趋势。Agent 会自动解析你要查询的地块/站点、时间范围，从本地业务库查出数据，并用图表展示。可以问趋势、对比、超标情况等。",
    examples: [
      "北区1号墒情站最近7天含水量趋势",
      "南区哪些地块盐分超标了？",
      "各墒情站最新平均含水量对比",
    ],
  },
  "knowledge-agent": {
    name: "农业知识助手",
    desc: "农业知识问答：盐碱地/灌溉/施肥，回答带出处",
    usage: "输入农业相关的知识问题，如盐碱地治理、灌溉时机、施肥建议等。Agent 会从知识库检索相关资料，结合农业领域知识回答，并标注信息来源出处，方便核对。",
    examples: ["盐碱地怎么治理？", "土壤含水量多少适合灌溉？"],
  },
  "diagnosis-agent": {
    name: "预警诊断助手",
    desc: "预警诊断：对墒情/盐碱异常给诊断报告",
    usage: "对监测数据中的异常（如盐分超标、含水量异常）进行诊断。Agent 会先查证实际数据作为证据，再结合农业知识库给出诊断结论和治理建议，每条建议都标明出处。",
    examples: ["南区块盐分超标了吗？诊断一下并给建议"],
  },
  "daily-report-agent": {
    name: "日报助手",
    desc: "日报：汇总各区墒情、气象、预警生成日报",
    usage: "一键生成农业物联网日报。Agent 会汇总各区域的墒情（含水量/盐分）、气象情况、预警信息，整理成一份结构化的日报，含异常标注和明日关注建议。",
    examples: ["生成今天的农业物联网日报"],
  },
  "graph-agent": {
    name: "图谱推理助手",
    desc: "图谱推理：某事物的治理方法/关联关系",
    usage: "基于自建的农业知识图谱（三元组 + 社区发现 + 子图检索）回答问题，特别适合「某事物有哪些治理方法」「A 与 B 有什么关系」这类关系型问题。回答会基于图谱结构推理。",
    examples: ["盐碱地有哪些治理方法？", "灌溉决策会影响什么？"],
  },
  // ---- 10 个模板自带 Agent ----
  "chatbot": {
    name: "通用聊天",
    desc: "简单的通用对话机器人",
    usage: "最基础的对话 Agent，用于测试平台连通性或简单的日常对话。没有连接外部工具，只做简单回复。",
    examples: ["你好", "介绍一下你自己"],
  },
  "research-assistant": {
    name: "联网研究助手",
    desc: "带网络搜索和计算器的研究助手",
    usage: "可调用网络搜索和计算器工具的助手，适合需要实时信息或计算的问题。依赖外部工具可用性。",
    examples: ["帮我查一下今天的天气"],
  },
  "rag-assistant": {
    name: "知识库问答助手",
    desc: "RAG 助手，可访问数据库中的信息",
    usage: "基于检索增强生成（RAG）的问答助手，从配置的知识库中检索信息回答。模板自带示例。",
    examples: ["这个系统有什么功能？"],
  },
  "command-agent": {
    name: "指令执行助手",
    desc: "可执行指令的 Agent",
    usage: "模板自带的示例 Agent，展示了如何让 Agent 调用工具执行指令。",
    examples: ["执行一个测试任务"],
  },
  "bg-task-agent": {
    name: "后台任务助手",
    desc: "周期性后台任务 Agent",
    usage: "演示周期性地在后台运行任务的功能，适合定时任务相关的展示。",
    examples: ["设置一个定时提醒"],
  },
  "langgraph-supervisor-agent": {
    name: "主管调度 Agent",
    desc: "LangGraph 主管调度，协调多个子 Agent",
    usage: "主管（supervisor）模式的 Agent，可协调调度多个工作子 Agent 协作完成任务。模板自带示例。",
    examples: ["调度一个研究工作"],
  },
  "langgraph-supervisor-hierarchy-agent": {
    name: "层级主管调度 Agent",
    desc: "带嵌套层级的主管调度 Agent",
    usage: "更复杂的主管调度模式，支持多级嵌套的 agent 层级协作。模板自带示例。",
    examples: ["演示多级协作"],
  },
  "interrupt-agent": {
    name: "中断交互 Agent",
    desc: "使用中断机制与用户交互的 Agent",
    usage: "演示 Agent 在执行过程中通过中断机制暂停并向用户请求确认或输入的功能。",
    examples: ["演示一次中断交互"],
  },
  "knowledge-base-agent": {
    name: "知识库检索 Agent",
    desc: "基于向量知识库的检索增强生成 Agent",
    usage: "从向量知识库检索信息并生成的 Agent。注意：依赖外部知识库服务（如 Bedrock KB）的配置，未配置时可能不可用。",
    examples: ["检索知识库内容"],
  },
  "github-mcp-agent": {
    name: "GitHub 管理助手",
    desc: "带 MCP 工具的 GitHub 仓库管理与开发 Agent",
    usage: "通过 MCP 工具管理 GitHub 仓库，可执行仓库管理、开发工作流等操作。依赖 GitHub 访问凭证。",
    examples: ["查看我的 GitHub 仓库"],
  },
};

// 左侧"试试这些问题"示例（复用 AGENT_META 的 examples）
const EXAMPLE_QS: Record<string, string[]> = Object.fromEntries(
  Object.entries(AGENT_META).map(([k, v]) => [k, v.examples])
);

export default function App() {
  const [agents, setAgents] = useState<AgentInfo[]>([]);
  const [current, setCurrent] = useState<string>("sql-data-agent");
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [backendDown, setBackendDown] = useState(false);
  const [showGuide, setShowGuide] = useState(false);
  const scrollRef = useRef<HTMLDivElement>(null);
  const abortRef = useRef<AbortController | null>(null);
  const sendRef = useRef<(q?: string) => void>(() => {});

  useEffect(() => {
    fetchAgents()
      .then((a) => {
        setAgents(a);
        setBackendDown(false);
      })
      .catch(() => setBackendDown(true));
  }, []);

  useEffect(() => {
    scrollRef.current?.scrollTo(0, scrollRef.current.scrollHeight);
  }, [msgs]);

  const resetChat = () => setMsgs([]);

  const send = useCallback(async (overrideQ?: string) => {
    const q = (overrideQ ?? input).trim();
    if (!q || loading) return;
    sendRef.current = send;
    setInput("");
    // 追加用户消息
    setMsgs((m) => [...m, { role: "user", blocks: [{ type: "text", text: q }] }]);
    // 追加空的助手消息（流式填充）
    const assistantIndex = msgs.length + 1;
    setMsgs((m) => [...m, { role: "assistant", blocks: [], streaming: true }]);
    setLoading(true);
    const controller = new AbortController();
    abortRef.current = controller;

    const pub = (fn: (blocks: ContentBlock[]) => ContentBlock[]) => {
      setMsgs((m) =>
        m.map((mm, i) => (i === assistantIndex ? { ...mm, blocks: fn(mm.blocks) } : mm))
      );
    };

    try {
      const tokenText: string[] = [];
      const tools: string[] = [];

      await streamAgent(
        current,
        q,
        (ev: StreamEvent) => {
          const t = ev.type;
          if (t === "token" && typeof ev.content === "string") {
            // 只累加 token（增量），这是构建最终文本的唯一来源
            tokenText.push(ev.content);
            pub((b) => [...b.filter((x) => x.type !== "text"), { type: "text", text: tokenText.join("") }]);
          } else if (t === "message") {
            const c = ev.content;
            if (c && typeof c === "object") {
              // 只取 tool_calls 名（显示 chips），不再追加 content 文本（避免重复）
              if (c.tool_calls) {
                const newTools: string[] = [];
                c.tool_calls.forEach((tc: any) => {
                  const n = tc.name;
                  if (n && !tools.includes(n)) {
                    tools.push(n);
                    newTools.push(n);
                  }
                });
                if (newTools.length) {
                  pub((b) => [...b, ...newTools.map((n) => ({ type: "tool" as const, name: n }))]);
                }
              }
            }
          } else if (t === "error") {
            pub((b) => [...b, { type: "text", text: "⚠️ " + (typeof ev.content === "string" ? ev.content : "出错了") }]);
          }
        },
        controller
      );

      // 流结束后：从完整文本中提取嵌入的 ECharts JSON，渲染成图表并移除该段
      const fullText = tokenText.join("");
      const chart = extractChart(fullText);
      if (chart) {
        // 精确定位图表 JSON 的起止（与 extractChart 一致的括号定位），整段删除
        const start = fullText.indexOf('{"title"');
        let cleaned = fullText;
        if (start >= 0) {
          let depth = 0;
          let end = -1;
          for (let i = start; i < fullText.length; i++) {
            if (fullText[i] === "{") depth++;
            else if (fullText[i] === "}") {
              depth--;
              if (depth === 0) {
                end = i + 1;
                break;
              }
            }
          }
          if (end > 0) {
            cleaned = fullText.slice(0, start) + fullText.slice(end);
          }
        }
        pub((b) => [
          ...b.filter((x) => x.type !== "text"),
          { type: "text", text: cleaned },
          { type: "chart", option: chart },
        ]);
      }
    } catch (e: any) {
      if (e.name !== "AbortError") {
        pub((b) => [
          ...b,
          { type: "text", text: "⚠️ 调用失败，请确认后端服务(8002)已启动。" },
        ]);
      }
    } finally {
      pub((b) => b);
      setMsgs((m) => m.map((mm, i) => (i === assistantIndex ? { ...mm, streaming: false } : mm)));
      setLoading(false);
      abortRef.current = null;
    }
  }, [input, loading, current, msgs]);

  // 从 ai 文本里提取嵌入的 chart JSON（ECharts option，特征为含 "series" 的对象）
  const extractChart = (text: string): any => {
    // 从文本中寻找以 {"title" 开头的 ECharts option JSON
    const idx = text.indexOf('{"title"');
    if (idx < 0) return null;
    const candidate = text.slice(idx);
    try {
      // 尝试解析从 idx 开始的完整 JSON 对象（到匹配的结束括号）
      const obj = JSON.parse(candidate);
      if (obj && (obj.series || obj.xAxis)) return obj;
    } catch {
      // 可能是文本后还有内容，尝试逐字符找括号闭合
      let depth = 0;
      let end = -1;
      for (let i = 0; i < candidate.length; i++) {
        if (candidate[i] === "{") depth++;
        else if (candidate[i] === "}") {
          depth--;
          if (depth === 0) {
            end = i + 1;
            break;
          }
        }
      }
      if (end > 0) {
        try {
          const obj = JSON.parse(candidate.slice(0, end));
          if (obj && (obj.series || obj.xAxis)) return obj;
        } catch {
          return null;
        }
      }
    }
    return null;
  };

  const stop = () => abortRef.current?.abort();

  return (
    <div className="app">
      <header className="topbar">
        <div className="logo">🌾 BizAgent</div>
        <div className="subtitle">农业物联网数据智能平台</div>
        {backendDown && <div className="warn">⚠️ 后端服务未连接（8002）</div>}
      </header>

      <div className="layout">
        {/* 左侧：agent 选择 */}
        <aside className="sidebar">
          <div className="side-title">选择 Agent</div>
          {agents.map((a) => (
            <div
              key={a.key}
              className={`agent-card ${current === a.key ? "active" : ""}`}
              onClick={() => {
                setCurrent(a.key);
                resetChat();
              }}
            >
              <div className="agent-name">
                {AGENT_META[a.key]?.name || a.name || a.key}
              </div>
              <div className="agent-desc">
                {AGENT_META[a.key]?.desc || a.description || "..."}
              </div>
            </div>
          ))}

          <div className="example-box">
            <div className="side-title">💡 试试这些问题</div>
            {(EXAMPLE_QS[current] || []).map((q, i) => (
              <div
                key={i}
                className="example-q"
                onClick={() => {
                  setInput(q);
                  // 直接触发发送（send 是稳定的 useCallback，接收可选问题参数）
                  send(q);
                }}
              >
                {q}
              </div>
            ))}
          </div>
        </aside>

        {/* 右侧：聊天 */}
        <main className="chat-panel">
          <div className="chat-header">
            <span className="current-name">
              {AGENT_META[current]?.name || current}
            </span>
            <div className="header-actions">
              <button className="guide-btn" onClick={() => setShowGuide(true)}>
                📖 使用说明
              </button>
              <button className="reset-btn" onClick={resetChat}>清空</button>
            </div>
          </div>

          <div className="msgs" ref={scrollRef}>
            {msgs.length === 0 && (
              <div className="empty">
                <div className="empty-icon">🤖</div>
                <p>选择左侧 Agent，输入或点击示例问题开始</p>
              </div>
            )}
            {msgs.map((m, i) => (
              <div key={i} className={`msg ${m.role}`}>
                {m.role === "assistant" &&
                  Array.isArray(m.blocks) &&
                  m.blocks.length === 0 &&
                  m.streaming ? (
                  <div className="typing">正在思考…</div>
                ) : (
                  <MessageContent blocks={m.blocks || []} />
                )}
              </div>
            ))}
          </div>

          <div className="input-bar">
            <textarea
              value={input}
              onChange={(e) => setInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === "Enter" && !e.shiftKey) {
                  e.preventDefault();
                  send();
                }
              }}
              placeholder="输入问题，Enter 发送，Shift+Enter 换行"
              rows={2}
            />
            {loading ? (
              <button className="send-btn stop" onClick={stop}>停止</button>
            ) : (
              <button className="send-btn" onClick={() => send()} disabled={!input.trim()}>
                发送
              </button>
            )}
          </div>
        </main>
      </div>

      {/* 使用说明弹窗 */}
      {showGuide && (() => {
        const meta = AGENT_META[current];
        const name = meta?.name || current;
        const desc = meta?.desc || agents.find((x) => x.key === current)?.description || "";
        const usage = meta?.usage || "暂无详细使用说明。";
        const examples = meta?.examples || [];
        return (
          <div className="modal-mask" onClick={() => setShowGuide(false)}>
            <div className="modal" onClick={(e) => e.stopPropagation()}>
              <div className="modal-header">
                <span className="modal-title">📖 {name} · 使用说明</span>
                <button className="modal-close" onClick={() => setShowGuide(false)}>✕</button>
              </div>
              <div className="modal-body">
                <div className="guide-section">
                  <div className="guide-label">功能简介</div>
                  <div className="guide-text">{desc}</div>
                </div>
                <div className="guide-section">
                  <div className="guide-label">使用方式</div>
                  <div className="guide-text">{usage}</div>
                </div>
                {examples.length > 0 && (
                  <div className="guide-section">
                    <div className="guide-label">使用例子（点击填入输入框）</div>
                    <div className="guide-examples">
                      {examples.map((q, i) => (
                        <div
                          key={i}
                          className="guide-example"
                          onClick={() => {
                            setInput(q);
                            setShowGuide(false);
                          }}
                        >
                          💬 {q}
                        </div>
                      ))}
                    </div>
                  </div>
                )}
              </div>
            </div>
          </div>
        );
      })()}
    </div>
  );
}
