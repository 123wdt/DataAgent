"""验证 FastAPI 服务能识别 sql-data-agent 并完成 SSE 流式查询。"""
import json, urllib.request, urllib.error

secret = None
for line in open(".env", encoding="utf-8"):
    line = line.strip()
    if line.startswith("AUTH_SECRET="):
        secret = line.split("=", 1)[1]

BASE = "http://127.0.0.1:8002"

def call(method, path, body=None, timeout=180):
    data = json.dumps(body).encode() if body else None
    req = urllib.request.Request(BASE + path, data=data, method=method)
    req.add_header("Content-Type", "application/json")
    if secret:
        req.add_header("Authorization", "Bearer " + secret)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read().decode()
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()

# 1) /info agent 列表
st, body = call("GET", "/info")
if st == 200:
    d = json.loads(body)
    agents = [a.get("key") for a in d.get("agents", [])]
    print("agent列表:", agents)
    print("含 sql-data-agent:", "sql-data-agent" in agents)
else:
    print("/info ->", st, body[:200])

# 2) SSE 流式调用 sql-data-agent（走 /{agent_id}/stream）
print("\n=== SSE /stream: 南区块哪个地区盐分超标 ===")
st, body = call("POST", "/sql-data-agent/stream", {
    "message": "南区块哪个地区盐分超标？",
    "model": "openai-compatible",
})
print("status:", st)
# 解析 SSE 事件（token 累积 + message 快照 + tool 标注）
token_text = []
ai_full = []
tool_names = []
for line in body.splitlines():
    if line.startswith("data: "):
        payload = line[6:]
        try:
            ev = json.loads(payload)
        except (json.JSONDecodeError, TypeError):
            continue
        typ = ev.get("type")
        if typ == "token":
            token_text.append(ev.get("content", ""))
        elif typ == "message":
            c = ev.get("content", {})
            if isinstance(c, dict):
                t = c.get("type")
                if t == "ai" and c.get("content"):
                    ai_full.append(c["content"])
                if c.get("tool_calls"):
                    tool_names.extend(tc.get("name", "") for tc in c["tool_calls"])
            elif isinstance(c, str) and c:
                ai_full.append(c)
        elif typ == "error":
            print("!!! SSE error:", ev.get("content"))
tokens = "".join(token_text)
final = "".join(ai_full) or tokens
print(f"token块数: {len(token_text)}, tool调用: {sorted(set(tool_names))}")
print("回答/流式摘要:", final[:400])
_has_error = False
for l in body.splitlines():
    if l.startswith("data: ") and l[6:].strip() not in ("[DONE]",):
        try:
            if json.loads(l[6:]).get("type") == "error":
                _has_error = True
        except (json.JSONDecodeError, TypeError):
            pass
print("\nSSE 测试完成 | 是否报错:", _has_error)
