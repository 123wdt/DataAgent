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

const AGENT_DESC: Record<string, string> = {
  "sql-data-agent": "自然语言查数：问含水量/盐分/气象，自动查数据库并出图表",
  "knowledge-agent": "农业知识问答：盐碱地/灌溉/施肥，回答带出处",
  "diagnosis-agent": "预警诊断：对墒情/盐碱异常给诊断报告",
  "daily-report-agent": "日报：汇总各区墒情、气象、预警生成日报",
  "graph-agent": "图谱推理：某事物的治理方法/关联关系",
};

// 根据 agent 提供的示例问题
const EXAMPLE_QS: Record<string, string[]> = {
  "sql-data-agent": [
    "北区1号墒情站最近7天含水量趋势",
    "南区哪些地块盐分超标了？",
    "各墒情站最新平均含水量对比",
  ],
  "knowledge-agent": ["盐碱地怎么治理？", "土壤含水量多少适合灌溉？"],
  "diagnosis-agent": ["南区块盐分超标了吗？诊断一下并给建议"],
  "daily-report-agent": ["生成今天的农业物联网日报"],
  "graph-agent": ["盐碱地有哪些治理方法？"],
};

export default function App() {
  const [agents, setAgents] = useState<AgentInfo[]>([]);
  const [current, setCurrent] = useState<string>("sql-data-agent");
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [input, setInput] = useState("");
  const [loading, setLoading] = useState(false);
  const [backendDown, setBackendDown] = useState(false);
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
              <div className="agent-name">{a.name || a.key}</div>
              <div className="agent-desc">
                {AGENT_DESC[a.key] || a.description || "..."}
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
            <span className="current-name">{current}</span>
            <button className="reset-btn" onClick={resetChat}>清空</button>
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
    </div>
  );
}
