"""Agent 轻量可观测（Tracing）：记录每次运行的步骤、工具调用、耗时，输出 JSON 日志。

设计（interview 亮点：不做黑盒，能看 Agent 每一步在想什么/做了什么）：
- 用 LangGraph 的 astream 逐事件消费，把「模型产出 + 工具调用 + 工具返回」按时间线落盘。
- 输出 JSONL（每行一条运行记录），可被前端/监控消费，也便于排查。
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from agents.sql_data_agent.embeddings import PROJECT_ROOT

LOG_DIR = PROJECT_ROOT / "logs" / "traces"


def _now() -> float:
    return time.time()


async def run_with_trace(
    graph,
    messages: list,
    config: dict | None = None,
    trace_dir: Path = LOG_DIR,
    session: str | None = None,
) -> tuple[list, list[dict]]:
    """带追踪地运行 agent。

    返回 (最终 messages, trace 步骤列表)。
    trace 每步: {ts, type: model|tool|result, name, content, duration}
    """
    import uuid

    config = dict(config or {})
    config.setdefault("recursion_limit", 50)
    session = session or uuid.uuid4().hex[:8]
    trace_dir.mkdir(parents=True, exist_ok=True)
    trace: list[dict] = []
    t_start = time.time()

    async for event in graph.astream(
        {"messages": messages},
        config=config,
        stream_mode="updates",
    ):
        for node, payload in event.items():
            ts = time.time() - t_start
            if node == "model" and isinstance(payload, dict):
                msgs = payload.get("messages", [])
                last = msgs[-1] if msgs else None
                entry = {"ts": round(ts, 3), "session": session, "node": "model",
                         "type": "llm"}
                if last is not None:
                    entry["content"] = (getattr(last, "content", "") or "")[:500]
                    if getattr(last, "tool_calls", None):
                        entry["tool_calls"] = [
                            {"name": tc.get("name"), "args": tc.get("args")}
                            for tc in last.tool_calls
                        ]
                trace.append(entry)
            elif node == "tools":
                trace.append({"ts": round(ts, 3), "session": session,
                              "node": "tools", "type": "tool_exec"})

    # 落盘 JSONL
    out_file = trace_dir / f"{session}.jsonl"
    with open(out_file, "w", encoding="utf-8") as f:
        for entry in trace:
            f.write(json.dumps(entry, ensure_ascii=False, default=str) + "\n")

    # 最终消息
    final = await graph.ainvoke({"messages": messages}, config=config)
    trace.append({"ts": round(time.time() - t_start, 3), "session": session,
                  "node": "done", "type": "summary",
                  "steps": len(trace), "duration_s": round(time.time() - t_start, 2)})
    return final["messages"], trace
