# Phase G–J 本地 Retrieval Hub、Codex MCP 与 Dashboard 报告

日期：2026-09-24

## 结论

第一部分已在本地仓库建立，不再依赖外部 GitHub 后端。版本化数据库、解析/分块、FTS5、Policy ranking、HTTP、stdio MCP 和 Streamable HTTP MCP 均已形成可执行闭环。

本机 Codex 已注册 `internalResearch` stdio MCP，并完成一次只读真实会话：模型调用 `search_documents`、`search` 和 `fetch`，随后输出文档事实、模型推断、不确定性、缺失信息和文档 URL。

## 实现范围

- `backend/src/research_hub/database.py`：SQLite WAL、显式 migration、source/document/version/page/chunk/FTS/Policy。
- `parsing.py` 与 `chunking.py`：文本、JSON、EML、文本层 PDF和边界感知 chunk。
- `service.py`：幂等/版本化 ingest、FTS5、过滤、来源权重、新鲜度、citation。
- `api.py`：API 1.0.0、Read/Admin Token、请求大小、统一错误和 409。
- `mcp_server.py`：只读 `search`、`fetch`、`search_documents` 与分析引导 instructions。
- `cli.py`/`runtime.py`：初始化、虚构数据、导入、搜索、HTTP 服务、stdio MCP 和 Codex 配置样例。

## 自动测试

- Dashboard/客户端：27 个 Node 测试通过。
- 后端：14 个测试通过，覆盖 migration、版本化、解析、chunk、检索、过滤、Policy、HTTP、MCP 内部调用和真实 stdio 子进程。
- 后端 OpenAPI 覆盖归档契约的全部 path/schema。
- Vite 生产构建通过。

统一命令：

```bash
npm test
```

## Live HTTP 与 MCP

本地 `127.0.0.1:8765` fixture Hub 实测：

- `check:live`：passed；health/status/sources/policy/search/fetch 一致，Policy v1。
- Streamable HTTP `/mcp`：初始化成功；发现 `fetch/search/search_documents`；高级搜索返回 Policy v1。
- stdio：独立进程初始化、list_tools、search 调用成功。
- Codex 全局配置：`internalResearch` enabled，stdio command 指向项目虚拟环境和本地数据目录。

## Codex 分析验收

测试问题要求模型只使用 `internalResearch`，搜索“芯片需求”、读取最相关资料，并严格区分事实和推断。

实际行为：

1. Codex 先调用 `search_documents` 和 `search`。
2. 首次连续词查询无结果后，主动以“芯片”等更宽查询重试。
3. 对命中文档调用 `fetch`。
4. 输出虚构标识、文档事实、需求到采购的推断链、资本开支不确定性、证据不足和 URL。

这证明模型可以利用 MCP 证据完成分析，而 Server 没有替模型预制判断。

## 实测发现与修复

问题：初版把连续中文查询的全部 bigram 用 AND 连接，“芯片需求”要求文档出现跨词 bigram“片需”，导致相关文档漏召回。

修复：同一个连续中文 run 内使用 bigram OR，不同空格分隔 run 和英文有效词之间使用 AND；常见英文问句停用词不进入约束。

复测：“芯片需求”通过 Streamable HTTP MCP 直接返回两份虚构资料，不再依赖模型二次回退。

## Dashboard Live 与排序一致性验收

- 浏览器连接真实本地 Hub 后，以“芯片需求”命中两份 fixture 文档。
- 将 `demo_filings` 权重从 1 提高到 3、将 `demo_research` 从 1 降到 0.5，保存后 Policy 从 v3 推进到 v4。
- 下一次服务端检索中，filings 从第 2 位升至第 1 位，research 从第 1 位降至第 2 位；UI 仅展示服务端顺序和位次变化，没有重算 score。
- 恢复两者权重为 1，Policy 推进到 v5，避免测试配置污染后续使用。
- HTTP 与 Streamable HTTP MCP 的同查询结果 ID 和 Policy 版本已通过自动脚本对比。

## 未完成边界

- 当前会话不会因修改 `~/.codex/config.toml` 自动获得新 MCP；需要新 Codex 会话。独立 Codex CLI 新会话已验证成功。
- ChatGPT 真机仍需要 Developer mode/workspace policy，以及 Secure MCP Tunnel 或可达 HTTPS `/mcp`。
- 真实 Capital IQ 文档尚未处理；必须另行确认授权和受控目录。
