# Internal Research MCP

本项目把版本化本地资料库、Retrieval Policy、HTTP API、只读 MCP Server 和买方研究 Dashboard 放在同一个仓库中。目标是让 Codex/ChatGPT 先搜索和读取授权资料，再基于可定位的原文证据完成分析判断。

当前开发版本：`0.2.0-dev`。真实研报、Token、运行数据库和模型文件不得提交到 Git。

## 架构

```text
仓库外文件 → 解析/版本/page/chunk → FTS5 ─┐
                                  dense vectors ─┼→ hybrid ranking
                                  concept config ┘       ├→ HTTP → Dashboard
                                                        └→ MCP → Codex/ChatGPT
```

MCP 只提供证据，不提供 `analyze` 或 `investment_decision` 工具。Codex/ChatGPT 负责比较资料、识别冲突并形成判断，同时区分文档事实、模型推断和信息缺口。

## 环境要求

- Node.js 22.18+
- Python 3.11+
- macOS/Linux；Windows 使用 `.venv\Scripts\python.exe` 替换示例中的 Python 路径

## 一次性安装

```bash
npm install
python3 -m venv backend/.venv
backend/.venv/bin/pip install -e 'backend[dev]'
```

所有 Python 依赖只安装到 `backend/.venv`。

需要真实语义检索时再安装本地 embedding 依赖：

```bash
backend/.venv/bin/pip install -e 'backend[semantic]'
```

## 启动完整本地 Demo

### 1. 初始化 Hub

```bash
backend/.venv/bin/research-hub --data-dir backend/data/hub init
backend/.venv/bin/research-hub --data-dir backend/data/hub demo
```

`init` 创建两个本地 Token，并生成：

- `backend/data/hub/access.local.json`
- `backend/data/hub/codex-mcp.local.toml`

两者均已被 Git 忽略。不要把内容复制到 issue、日志或提交中。

### 2. 启动 HTTP + Streamable HTTP MCP

本机单人 Demo 可显式关闭 HTTP Bearer 校验；认证实现仍保留，且服务仍只绑定 `127.0.0.1`：

```bash
backend/.venv/bin/research-hub \
  --data-dir backend/data/hub \
  serve --port 8765 --cors-origin http://127.0.0.1:5173 --local-no-auth
```

需要恢复 Token 校验时，去掉 `--local-no-auth`，使用原命令：

```bash
backend/.venv/bin/research-hub \
  --data-dir backend/data/hub \
  serve --port 8765 --cors-origin http://127.0.0.1:5173
```

可用地址：

- Health：`http://127.0.0.1:8765/healthz`
- OpenAPI：`http://127.0.0.1:8765/docs`
- MCP：`http://127.0.0.1:8765/mcp`

### 3. 打开 Dashboard

新终端运行：

```bash
npm run dev
```

打开 Vite 显示的地址，通常是 `http://127.0.0.1:5173`。页面默认使用虚构 fixture；切换到 Live/上游 HTTP 模式后填写：

- Base URL：`http://127.0.0.1:8765`
- 本机无认证 Demo：保持“不启用 Token”勾选；
- Bearer 模式：取消勾选，再填写 `access.local.json` 中的 Read Token；保存 Retrieval Policy 时还需 Admin Token。

`--local-no-auth` 只用于本机临时验证，不能与公网 tunnel、非回环监听或共享机器部署组合。浏览器中的 Token 也只适合受控本地演示；生产形态必须使用服务端代理或正式认证。

## 导入仓库外资料

先创建数据源，再导入文件或目录：

```bash
backend/.venv/bin/research-hub --data-dir backend/data/hub \
  source --id local_research --name 'Local Research' --kind local

backend/.venv/bin/research-hub --data-dir backend/data/hub \
  ingest /absolute/path/to/authorized/files \
  --source-id local_research --source-name 'Local Research'
```

支持 TXT、Markdown、JSON、JSONL、EML、有文本层的 PDF，以及直接读取包含这些格式的 ZIP；ZIP 条目不会先解压到仓库。RAR 暂不作为原生容器支持，需先在受控临时目录解包。扫描 PDF 会报告解析失败/OCR required；本阶段不会静默调用外部 OCR。重复导入同一内容为 `unchanged`，内容变化会创建不可变 `document_version`。大型目录或 ZIP 会按文档数和正文字符数自动分批写入。

真实 Capital IQ 抽样验收记录见 [`docs/memos/REAL_DATA_ACCEPTANCE_2026-09-24.md`](docs/memos/REAL_DATA_ACCEPTANCE_2026-09-24.md)。原始归档、抽取正文、运行数据库和凭据均不得提交到 Git。

导入或更新文档后构建本地 dense-vector 索引：

```bash
backend/.venv/bin/research-hub --data-dir backend/data/hub semantic-build
backend/.venv/bin/research-hub --data-dir backend/data/hub semantic-status
```

公开多语模型只在首次构建时下载；文档、chunk 和生成向量不离开本机。索引与当前 chunk 数量/最大 ID 不一致时，查询自动退回概念增强的 FTS，不会使用陈旧向量。

## 连接 Codex MCP

打开 `backend/data/hub/codex-mcp.local.toml`，将其中配置复制到本机 Codex 的 `~/.codex/config.toml`。也可以直接运行（路径按实际仓库位置替换）：

```bash
codex mcp add internalResearch -- \
  '/absolute/path/backend/.venv/bin/python' -m research_hub.cli \
  --data-dir '/absolute/path/backend/data/hub' stdio
```

上面的 `backend/data/hub` 是初始化/样例库。已经完成真实资料索引时，应使用独立名称指向实际索引目录，避免 Prompt 误调用空的样例库：

```bash
codex mcp add internalResearchReal -- \
  '/absolute/path/backend/.venv/bin/python' -m research_hub.cli \
  --data-dir '/absolute/path/backend/data/real-test' stdio
```

然后确认服务器出现在列表中：

```bash
codex mcp list
codex mcp get internalResearchReal
```

生成的 stdio 配置使用当前虚拟环境 Python和绝对数据目录。若移动仓库，应重新注册。注册后新开 Codex 会话，让工具清单重新发现；Prompt 中明确写“仅使用 `internalResearchReal` MCP”。

建议在新 Codex 会话中测试：

```text
请先搜索“芯片需求”，读取最相关的两份资料，然后：
1. 分别列出文档明确陈述的事实；
2. 比较观点差异；
3. 给出你的分析判断；
4. 标注哪些是推断、哪些信息仍缺失；
5. 引用返回的文档 URL 和页码/字符范围。
```

预期工具顺序是 `search_documents → fetch → 分析回答`。标准 `search` 用于低 token 候选发现。

## 连接 ChatGPT

ChatGPT 不能直接访问宿主机的 `127.0.0.1`。按照当前 [OpenAI MCP Server 文档](https://developers.openai.com/plugins/build/mcp-server) 和 [ChatGPT 连接流程](https://developers.openai.com/plugins/deploy/connect-chatgpt)，开发者模式需要以下之一：

- 可达的 HTTPS Streamable HTTP MCP endpoint，通常以 `/mcp` 结尾；或
- [Secure MCP Tunnel](https://developers.openai.com/api/docs/guides/secure-mcp-tunnels)，把私有 stdio/HTTP MCP 安全转发给 ChatGPT。

本仓库不自动创建公网入口，也不保存 tunnel ID。账户 Developer mode、workspace policy、认证和引用 URL 可达性到位后，再按 `docs/memos/EXTERNAL_ACCEPTANCE.md` 执行阶段 K 验收。

## MCP tools

| Tool | 用途 |
|---|---|
| `search(query)` | 使用当前 Policy 返回轻量 `id/title/url` 候选 |
| `fetch(id)` | 读取搜索结果对应的当前完整原文与 citation metadata |
| `search_documents(request)` | 使用 source/date/metadata filter，返回 snippet、score details 和 `policy_version` |

三个工具全部只读。来源、入库、删除和 Policy 写入只允许通过受管理 Token 保护的 HTTP/CLI 完成。

## 检索与排序

短句先由版本化投研概念配置识别公司、产品和产业链概念，再并行执行 FTS5 与本地 dense-vector 召回。两路候选在文档级用 Reciprocal Rank Fusion（RRF）融合，完全相同正文只保留得分最高的代表项，最后再应用来源与时间策略：

```text
hybrid_relevance = 60 / (60 + lexical_rank) + 40 / (60 + semantic_rank)
freshness = 0.5 ^ (age_days / half_life_days)
score = hybrid_relevance × source_weight × (1 + recency_boost × freshness)
```

Dashboard 只显示服务端顺序和 `score_details`，不会重新排序。`score` 只能在一次查询内比较，不是概率或事实置信度。

### 信息源 Ranking V0

V0 提供一个只含虚构来源的版本化 Priority 1–4 目录，并验证 canonical name/显式 alias、唯一主信息源及 Policy 更新后的下一次检索重排。它不连接邮箱，也不改变 MCP schema。

运行独立验收：

```bash
backend/.venv/bin/python backend/scripts/check_source_ranking_v0.py
```

创建一个不影响现有 Hub 的可运行虚构 V0 数据库：

```bash
backend/.venv/bin/research-hub \
  --data-dir backend/data/source-ranking-v0 \
  source-ranking-demo
```

如需从 Codex 交互测试，应把该独立目录注册成另一个 MCP 名称；不要覆盖当前 `internalResearch`，直到 V0 验收完成。

真实来源名单、多来源 attribution 和邮箱全量批次不能用 V0 结果替代；下面的 V1 只完成虚构持久化与批次完整性基线。

### 信息源 Ranking V1

V1 在独立 SQLite 数据库中持久化信息源、alias、document version attribution 和三文件夹邮件同步批次。它仍只使用虚构 EML/JSON，不连接真实账户。

```bash
backend/.venv/bin/research-hub \
  --data-dir backend/data/source-ranking-v1 \
  source-ranking-v1-demo

backend/.venv/bin/python backend/scripts/check_source_ranking_v1.py
```

同步后的主信息源会通过现有 `/api/sources` 出现在 Live Dashboard，并继续使用 `expected_version` 保存权重。alias 和批次详情暂不在 UI/MCP 暴露。

## 测试

```bash
npm test
```

该命令运行：

- 契约/生成物/评测漂移检查；
- TypeScript 类型检查和 Dashboard 单元测试；
- Python migration、版本化、解析、检索、Policy、HTTP 和 MCP 测试；
- Vite 生产构建。

单独运行后端测试：

```bash
backend/.venv/bin/python -m pytest -q -c backend/pyproject.toml backend/tests
```

## Capital IQ 后台监听（阶段 P）

安装本地 semantic extra 后，可用同一个进程轮询目录、幂等导入、构建 dense-vector generation，并在向量发布后把 item 标为 `processed`：

```bash
backend/.venv/bin/pip install -e 'backend[semantic]'

backend/.venv/bin/research-hub \
  --data-dir backend/data/automated-local \
  watch-folder '/absolute/path/to/Capital IQ Data' \
  --connector-id capital_iq_folder \
  --connector-name 'Capital IQ Folder' \
  --source-id capital_iq \
  --source-name 'Capital IQ' \
  --settle-seconds 5 \
  --max-queue-depth 1000 \
  --interval-seconds 15
```

这些数字是可覆盖的本地演示参数，不是生产 SLA 或容量承诺。单轮验证可增加 `--once`；启用稳定窗口时，新文件需要至少两次扫描才能进入队列。扫描 checkpoint、`size + mtime` 稳定性、内容哈希、队列背压、worker heartbeat 和删除 observation 都会持久化。原始文件不移动、不删除；同一路径内容变化会形成新的不可变 document version，源文件删除也不会清除历史证据。

无 Outlook 账号时，可运行完全虚构的 delta/附件闭环：

```bash
backend/.venv/bin/research-hub \
  --data-dir backend/data/outlook-fixture-local \
  outlook-fixture-demo
```

该命令不联网、不读取真实邮箱，验证两页 delta、checkpoint、正文/附件父子 item、V1 来源 alias 归因和向量发布。`OutlookDeltaClient` 与 `OCRAdapter` 已定义为可替换边界；扫描 PDF 未配置 OCR 时会阻止整封邮件进入 `processed`，测试 OCR 只用于自动化状态验证。

启动 HTTP 和 Dashboard 后，新增的“后台处理监控”显示待处理、处理中、已处理、失败、重试中和向量积压。监控 API 属于 OpenAPI 1.1.0；MCP 仍只有三个只读工具。

对已经建立、但早于 ingestion control-plane 的索引，Dashboard 可以立即做研究检索，但监控计数不会自动伪造为“已处理”。如需把历史导入映射到五态状态机，应执行单独的可审计 backfill；当前版本不根据文档表反推处理事件。

真实 Outlook 登录、Graph delta/附件下载和生产 OCR 尚未执行，需要账号授权与 OCR 选型后完成阶段 P3。

## 项目导航

- [MISSION.md](MISSION.md)：最终产品目标与完成定义
- [ROADMAP.md](ROADMAP.md)：阶段 A–P 和退出条件
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)：统一后端、HTTP、MCP 与 Dashboard 架构
- [docs/VERSION_ITERATION_LOG.md](docs/VERSION_ITERATION_LOG.md)：版本目标和决策变化
- [本地补全方案](docs/memos/FIRST_PART_LOCAL_COMPLETION_PLAN.md)：禁止项、Git 版本差异与实施计划
- [外部验收条件](docs/memos/EXTERNAL_ACCEPTANCE.md)：ChatGPT/真实资料验收门槛
- [MCP V0 信息源 Ranking](docs/memos/MCP_V0_SOURCE_RANKING.md)：虚构来源目录、解析与重排证据
- [MCP V1 邮件信息源 Ranking](docs/memos/MCP_V1_EMAIL_SOURCE_RANKING.md)：持久化归因、批次完整性与 MCP 重排
- [自动监听实施基线](docs/memos/AUTOMATED_INGESTION_MONITORING_PLAN.md)：状态口径、实施顺序和后续待办
- [API 契约](docs/contracts/openapi.json)：当前机器可读 API 1.1.0

## 当前限制

- dense 索引是可选本地构建产物；未安装模型、尚未构建或索引陈旧时自动回退概念增强 FTS。
- 当前 exact cosine 适合约 6 万 chunk 的本地验收；规模和 P95 达到阈值后迁移 ANN，而不是继续线性扫描。
- 扫描 PDF 已有 OCR adapter 和阻断状态机，但生产 OCR 引擎、复杂表格和版面仍待选型与受控验收。
- `fetch` 当前返回完整正文；长报告的 passage/range tool 需要正式契约升级。
- SQLite 适用于本地 Demo 和中小规模；队列、PostgreSQL/ANN 的升级由实际 P95、写锁和积压指标触发。
- ChatGPT 真机连接仍依赖账户能力和安全可达性，不能由本地自动测试替代。
