// 对接 BizAgent 后端 FastAPI 服务（8002）
// 通过 vite proxy：/api -> http://127.0.0.1:8002

export const BASE = "/api";

export interface AgentInfo {
  key: string;
  name?: string;
  description?: string;
}

/** 拉取全部可用 agent（/info） */
export async function fetchAgents(): Promise<AgentInfo[]> {
  const res = await fetch(`${BASE}/info`);
  if (!res.ok) {
    throw new Error(`拉取 agent 列表失败: ${res.status}`);
  }
  const data = await res.json();
  const list = data.agents ?? data;
  return list.map((a: any) => ({
    key: a.key ?? a.id,
    name: a.name ?? a.key ?? a.id,
    description: a.description ?? "",
  }));
}

export interface StreamEvent {
  type: string;
  content?: any;
  event?: string;
  data?: any;
}

/**
 * 通过 SSE 流式调用某个 agent。
 * onEvent: 每个解析出的 SSE data 事件回调。
 * 返回一个 Promise，流结束 resolve。
 */
export async function streamAgent(
  agentKey: string,
  message: string,
  onEvent: (ev: StreamEvent) => void,
  controller?: AbortController
): Promise<void> {
  const url = `${BASE}/${agentKey}/stream`;
  const body = JSON.stringify({
    message,
    model: "openai-compatible",
  });

  const resp = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body,
    signal: controller?.signal,
  });

  if (!resp.ok || !resp.body) {
    throw new Error(`调用 ${agentKey} 失败: ${resp.status}`);
  }

  const reader = resp.body.getReader();
  const decoder = new TextDecoder("utf-8");
  let buffer = "";

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    // 按行切分 SSE
    let idx: number;
    while ((idx = buffer.indexOf("\n")) >= 0) {
      const line = buffer.slice(0, idx).trim();
      buffer = buffer.slice(idx + 1);
      if (line.startsWith("data:")) {
        let payload = line.slice(5).trim();
        if (payload === "[DONE]") continue;
        try {
          const ev = JSON.parse(payload);
          onEvent(ev);
        } catch {
          /* 忽略无法解析的行 */
        }
      }
    }
  }
}
