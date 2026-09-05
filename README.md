# 🌾 BizAgent · 农业物联网数据智能 Agent 平台

一个面向**农业物联网（土壤墒情/盐碱监测）**的多 Agent 数据智能平台，基于
**LangGraph + FastAPI** 构建，提供 5 个业务 Agent，从"自然语言查数"到"诊断报告/日报/知识问答/图谱推理"全链路。

> 基于 agent-service-toolkit 二次开发，落地了完整的农业领域多 Agent 体系。

## 为什么做这个（面试叙事）

传统物联网平台只能"看数"，决策仍靠人工经验。本项目把大模型 Agent 接入农业物联数据底座，
让用户用**自然语言**提问，Agent 自动完成 **查数 → 分析 → 诊断 → 给建议** 的闭环，
且每一步"既有数据证明、又有知识出处"，可解释、可审计。

## 5 个业务 Agent

| Agent | 能力 | 核心技术 |
|-------|------|----------|
| **sql-data-agent** 查数 Agent | 自然语言查业务库，返回数据 + 图表 | NL2SQL + RAG-on-DDL + 只读安全三层 |
| **knowledge-agent** 知识 Agent | 农业知识问答，带 `[n]` 溯源 | 向量 + BM25 双路 + RRF 混合检索 |
| **diagnosis-agent** 诊断 Agent | 盐碱/墒情异常诊断报告 | 数据证明 run_sql + 建议出处 knowledge_search 双轨 |
| **daily-report-agent** 日报 Agent | 每天汇总墒情/气象/预警生成日报 | 多工具编排 + 结构化输出 |
| **graph-agent** GraphRAG Agent | 关系型问题（X 有哪些方法/关联） | 自实现知识图谱 + 社区检测 + 子图检索 |

服务端统一由 FastAPI 通过 **SSE 流式** 提供，前端（agent-chat-ui）经 `/info` 识别全部 agent 后对接。

## 差异化亮点（炫技点）

1. **RAG-on-DDL（自研）**：不喂业务数据，只喂"表结构 DDL"，让 Agent 自己学会拼 SQL
   查任意维度数据。DDL 解析 → bge-small-zh 向量化 → 检索表卡片。
2. **只读安全三层**：只读账号 + SQL 语法/关键词校验（拦截 DELETE/DROP/堆叠注入/系统表/越权表）+ 行数限制。
3. **混合检索**：向量（语义）+ 自实现 BM25（农业专业词精确匹配）+ RRF 融合，弥补向量检索对"g/kg、压盐"等低频词的短板。
4. **评测闭环（自实现 RAGAS 三指标）**：对知识 Agent 跑忠实度/相关度/上下文精度，真实跑分
   `忠实度 0.691 / 相关度 0.830 / 上下文精度 0.880`，且评测驱动优化（细看 docs/eval_dashboard.md）。
5. **GraphRAG 自实现**：纯 Python（无 networkx）实现农业知识图谱——45 节点、37 边，
   Louvain 社区检测自动分出"灌溉/治理/监测/耐盐"等主题社区，BFS 子图 + 社区上下文注入 LLM。
6. **语义缓存**：问题 embedding 余弦相似度命中即复用回答，同义问题零 LLM 调用。
7. **增量索引**：源文件 MD5 指纹，知识源没变就不重建（0.02s 跳过全量 embedding）。
8. **可观测追踪**：LangGraph 逐事件时间线（模型产出/工具调用/耗时）落盘 JSONL。

## 目录结构

```
src/
├── agents/
│   ├── sql_data_agent/    查数 Agent（RAG-on-DDL + 安全 + 图表 + SSE）
│   ├── knowledge_agent/   知识 Agent + 诊断 Agent（混合检索 / 双轨诊断）
│   ├── daily_report_agent.py  日报 Agent
│   ├── graph_agent.py         GraphRAG Agent
│   └── tracing.py             Agent 可观测追踪
├── cache/
│   ├── semantic_cache.py      语义缓存
│   └── index_fingerprint.py   增量索引指纹
├── graph/                     自实现 GraphRAG（三元组 + 社区 + 子图检索）
├── evaluation/                RAG 三指标评测 + 看板
├── core/                      模型接入（openai-compatible relay）
└── service/service.py         FastAPI 服务（/info /stream）
knowledge/                    农业知识库（知识 Agent 语料）
scripts/                       各类脚本/测试
docs/eval_dashboard.md         RAG 评测看板
```

## 快速开始

```sh
# .env 配好模型（本项目用 openai-compatible relay）
uv sync
# 构建 RAG-on-DDL 索引（读 scripts/db/schema.sql）
uv run python scripts/build_rag_ddl.py
# 启动服务（默认 8002）
cd src && uv run python run_service.py
# 调用
curl http://127.0.0.1:8002/info        # 查看全部 agent
# SSE 流式调用 sql-data-agent 等
```

## 测试脚本

| 脚本 | 验证内容 |
|------|----------|
| `scripts/test_safe_sql.py` | 只读安全（拦截 DELETE/DROP/越权） |
| `scripts/test_service.py` | 服务 SSE 流式无报错 |
| `scripts/e2e_w2.py` | 知识/诊断 Agent 端到端 |
| `src/evaluation/run_evaluation.py` | RAG 三指标评测（offline/full） |
| `scripts/test_semantic_cache.py` | 语义缓存命中 |
| `scripts/test_incremental_index.py` | 增量索引跳过重建 |
| `scripts/test_semantic_agent.py` | 语义缓存接入 Agent |

## 真实业务库

模拟 46 团土壤墒情业务库（`scripts/db/schema.sql` + 灌库脚本），含：
- `mon_soil_record`：土壤墒情记录（2 区域、6 墒情站、含水量/盐分/温度等）
- `mon_weather_record`：气象（温度/湿度/降雨/蒸发）
- `alert_soil_log`：土壤盐分预警日志
- 12960 条土壤记录，北区/南区、含水/盐分超阈值约束齐全
