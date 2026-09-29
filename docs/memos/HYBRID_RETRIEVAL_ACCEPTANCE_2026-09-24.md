# Hybrid Retrieval 真实库验收

日期：2026-09-24

## 目标

把“返回所有含芯片字样的报告”升级为面向买方研究短句的证据发现：查询可同时表达公司、产品型号、资本开支和 AI infrastructure 概念，系统用词法精度与语义召回互补，并继续受 source weight、freshness 和 metadata/date/source filter 控制。

## 实现

- `query_planner.py` 读取随包分发的 `finance-concepts-v1`，将“英伟达具体显卡”规划为 NVIDIA 实体组与 GPU 产品组。
- FTS5 和 FastEmbed `paraphrase-multilingual-MiniLM-L12-v2`（384 维）并行召回。
- 文档级 RRF 使用 lexical 60 / semantic 40 的精度优先权重；语义相似度低于 0.28 不进入候选。
- 最终 limit 前按 `body_sha` 折叠完全相同正文，再应用来源权重与新鲜度。
- dense index 缺失或与当前 chunk count/max ID 不一致时自动回退概念增强 FTS。

没有修改 OpenAPI 1.0.0、MCP tool schema 或 `fetch` 语义；HTTP、MCP 和 Dashboard 仍调用同一 `RetrievalHub.search`。

## 真实索引

| 项目 | 结果 |
|---|---:|
| Current chunks | 62,821 |
| Dense dimension | 384 |
| Vector matrix | 92 MB |
| Model cache | 240 MB |
| Semantic directory total | 333 MB |
| Corpus digest | `f27504ad…ed256` |
| Concept version | `finance-concepts-v1` |

索引和模型均位于 `backend/data/real-test/semantic/`，已被 Git 忽略。原始正文未发送到云端；仅首次下载公开 embedding 模型。

## 固定短句结果

`backend/scripts/evaluate_hybrid.py` 对四个短句比较 lexical-only 和 hybrid top 10。`expected_term_hit_rate` 只是证据词覆盖的可重复 smoke metric，不等于人工相关性标签。

| Query | Lexical top-k | Hybrid top-k | Hybrid 证据词覆盖 |
|---|---:|---:|---:|
| 英伟达具体显卡 | 10 | 10 | 100% |
| AI infra power and networking bottlenecks | 10 | 10 | 100%（包含 power/cooling/network/HBM/server 等任一证据词） |
| Nebius capex and GPU capacity | 8 | 10 | 100% |
| Snowflake AI product monetization | 10 | 10 | 100% |

Nebius 用例显示 dense recall 为严格词法条件之外补足 2 个候选。`Nebius` top 50 复查得到 0 个重复正文组，说明 154 个已知精确重复组不会再重复占结果位。

## 延迟

- 新进程第一次加载模型与索引的单次 hybrid 查询约 0.6 秒；首次验收进程观测到 0.62–1.04 秒。
- 同一常驻进程预热后运行 20 次：P50 38.64 ms，P95 70.12 ms，最小 33.06 ms，最大 77.76 ms。
- 该结果支持当前 62.8k chunk 使用本地 exact cosine；不是日增数百份后的永久架构结论。

## 仍需做的精度工作

- 当前证据词覆盖只是 smoke check；需要买方分析师对固定 query-document pair 做 relevance grade，并计算 nDCG@10、Recall@20 和 duplicate-adjusted precision。
- 概念表只覆盖少量公司/GPU/AI infra/Capex 词汇；扩展必须版本化并经过回归，不能堆成不可审计同义词库。
- dense 模型可能把产业链相关但问题不直接相关的报告带入结果；当前用 lexical 60 / semantic 40 保守融合，后续应按人工标注调参。
- 语义相似度不是事实可信度；最终判断仍需 `fetch` 原文并检查时点、主体和观点冲突。
- 日增数百份时必须改为增量 embedding 和后台 index generation 切换；exact cosine P95 持续超过 500 ms 或 chunk 达数十万后迁移 ANN。

## 复现

```bash
backend/.venv/bin/pip install -e 'backend[semantic]'
backend/.venv/bin/research-hub --data-dir backend/data/real-test semantic-build
backend/.venv/bin/research-hub --data-dir backend/data/real-test semantic-status
backend/.venv/bin/python backend/scripts/evaluate_hybrid.py --data-dir backend/data/real-test
npm test
```
