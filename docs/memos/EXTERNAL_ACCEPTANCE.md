# 外部验收备忘录

状态：本地 Hub/Codex MCP 与授权真实资料子集已通过；等待 ChatGPT 外部连接验收。

更新日期：2026-09-24

## 当前实测状态

- 本地 fixture Hub 已在 `127.0.0.1:8765` 通过 live HTTP 检查。
- stdio 与 Streamable HTTP MCP 均已完成真实初始化、工具发现和搜索调用。
- `internalResearch` 已注册到本机 Codex；新临时 Codex 会话完成 `search → fetch → 带引用分析`。
- 修改 MCP 配置不会给已经运行中的当前会话热添加工具；需要新会话。
- 用户已明确授权本轮处理所附 Capital IQ 资料。原始归档保持在仓库外，只把解析结果写入 Git ignore 的隔离测试库。
- 所附 802 份 PDF 已全部进入本地处理：792 份成功、9 份 `pdf_parse_failed`、1 份超过 20 MB 安全上限。
- 真实库 stdio MCP 与临时 Codex 会话完成 `search_documents → fetch → 事实/推断/冲突/缺口分析`；详细证据见 `REAL_DATA_ACCEPTANCE_2026-09-24.md`。

因此本地 HTTP/MCP/Codex fixture 和真实资料全量本地验收为 `passed_with_known_gaps`；ChatGPT developer mode、远程可打开引用仍为 `not_run`。10 份失败报告、重复正文折叠和 source/membership 语义仍需后续决策。

## 需要提供的外部输入

### 真实 HTTP / MCP

1. 可访问的 Retrieval Hub Base URL。
2. Read Token；策略更新复测另需 Admin Token。
3. 已配置到目标客户端的 Retrieval Hub MCP Server，并暴露 `search`、`fetch`；如需 Policy 版本精确对比，还需 `search_documents`。
4. 一条能稳定命中的脱敏测试查询。
5. 目标客户端能够访问的引用 URL；不得使用只对宿主机有效的 loopback URL 作为最终引用证据。

### Capital IQ 受控实验

1. 三家公司及各自允许匹配的公司名、ticker、曾用名和子公司别名。
2. 一个明确的自然月和时区口径。
3. 数据使用权限与允许输出的聚合指标范围。
4. 本仓库 Retrieval Hub 的受控外部数据目录；原始 PDF、数据库和抽取正文不得进入 Git。

## 到位后的执行顺序

```bash
export RESEARCH_HUB_BASE_URL='http://<controlled-host>:<port>'
export RESEARCH_HUB_READ_TOKEN='<read token>'
export RESEARCH_HUB_LIVE_QUERY='<de-identified query>'
npm --silent run check:live > /tmp/retrieval-http.json
```

随后在已配置的 Custom MCP Tools 中执行同一查询，把原始 MCP tool result 保存到临时文件：

```bash
npm run check:mcp-parity -- /tmp/retrieval-http.json /tmp/retrieval-mcp.json
```

最后只对最终需要引用的结果执行 MCP `fetch`，验证返回 ID 来自 search、URL 对目标客户端可达、回答包含引用，并把结论填入 `docs/evaluation/MCP_LIVE_TEMPLATE.md` 的副本。临时响应或内部文档 ID 不提交到仓库。

策略更新复测必须从 `GET /api/policy` 读取最新版本，使用 Admin Token 和最近读取的 `expected_version` 保存；更新后分别运行 HTTP 与 MCP 查询。测试结束应恢复原策略，恢复操作同样使用当时最新版本，409 时停止而不是覆盖他人修改。

## 完成判定

阶段 E 只有同时满足以下条件才可改为已完成：

- 真实 HTTP 检查通过并记录 payload/token 指标。
- HTTP 与 MCP 候选 ID 和顺序一致；高级工具可用时 Policy 版本也一致。
- MCP `search → fetch → 引用` 至少成功一组，引用 URL 对目标客户端可达。
- 策略更新后，HTTP 与 MCP 下一次查询体现新策略，且原策略已安全恢复或记录保留原因。
- 真实 metadata filter 有上游响应证据。
- 若执行 Capital IQ 实验，三家公司、月份、别名规则和数据权限均已版本化记录。

## 当前无需再决定的事项

- 本地临时部署继续使用系统分配端口，不固定端口、不常驻、不开放公网。
- Dashboard 不新增客户端 reranker、embedding、LLM 摘要或 PDF 解析器。
- 标准 MCP `search` 不提供 `policy_version` 时明确标记 `not_available`，不由客户端猜测。
