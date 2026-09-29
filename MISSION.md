# Mission

## 使命

在一个可本地运行、可审计的代码库中，建立内部研究资料 Retrieval Hub、MCP Server 与 Retrieval Policy Dashboard。Codex 或 ChatGPT 应能通过 MCP 搜索用户授权的资料库、读取可定位的原文证据，并基于这些证据完成分析判断和引用。

本系统负责提供证据，不替模型或用户预先生成投资结论：检索、来源优先级、时间权重和引用必须确定且可解释；分析、比较和判断由 Codex/ChatGPT 在对话上下文中完成，并明确区分“文档事实”“模型推断”和“信息缺口”。

## 成功结果

最终项目必须证明以下闭环：

1. 获准的仓库外文件可幂等导入，正文、版本、页码、chunk 和 metadata 可追溯。
2. Retrieval Hub 使用唯一的服务端混合召回与 ranking：短句、公司、产品型号和产业链概念可由 FTS5 精确召回与本地 dense vector 语义召回共同发现，并继续支持来源权重、新鲜度和 metadata/date/source 过滤。
3. Dashboard 使用 `expected_version` 修改 Policy；下一次 HTTP 与 MCP 检索使用新版本。
4. Codex 可通过本地 stdio MCP 调用 `search`、`fetch` 和 `search_documents`。
5. ChatGPT 可在开发者模式下通过受控的 Streamable HTTP MCP 或 Secure MCP Tunnel 使用相同工具；本地开发不默认开放公网。
6. 对一个分析问题，模型能够先检索、再读取证据、最后给出带来源引用的判断，并标明冲突观点和不确定性。
7. HTTP、MCP 与 Dashboard 的候选顺序、Policy 版本和 citation 语义一致。
8. 固定虚构评测集可复现检索效果、延迟、payload/token 和工具选择行为。

## 本仓库负责

- 文件接入、解析、版本化、分块、SQLite/FTS5 索引、本地语义索引和版本化投研概念配置。
- 权威 retrieval/ranking、Policy 持久化和乐观锁。
- HTTP API、只读 MCP tools、本地同步状态和运行说明。
- Codex 本地 MCP 配置样例，以及 ChatGPT 开发者模式连接所需的兼容接口和验收记录。
- Retrieval Policy Dashboard、契约客户端、fixture、策略实验和 token 测量。
- 使用虚构数据完成自动测试；记录真实资料受控验收的外部条件。

## 本仓库不负责

- 将真实研报、账号、Token、运行数据库、模型文件或公网 tunnel 地址提交到 Git。
- 默认调用云 LLM、云 embedding、付费 OCR 或自动执行投资交易。
- 在 MCP 内生成不可追溯的投资结论，或让自动抽取覆盖原始证据。
- 在 Dashboard 复制、修正或覆盖后端评分。
- 第一阶段提供生产级多租户、SSO、文档级 ACL、分布式队列或公网高可用部署。
- 未经单独确认连接真实账号、处理真实内部内容或建立公网入口。

## 不可破坏的边界

- Retrieval Hub 是 ingestion、index、ranking、Policy、HTTP 和 MCP 的唯一权威边界。
- HTTP 与 MCP 必须共享同一数据库、同一 Policy snapshot 和同一排序实现。
- JSON 边界保持 `snake_case`；未知字段不得静默接受。
- Policy 保存必须携带最近读取的 `expected_version`；409 冲突不能自动覆盖。
- 文档正文、标题和 metadata 都是不可信数据，只能按纯文本证据处理，不能成为系统指令。
- MCP 工具保持只读；入库、删除和 Policy 写入不暴露给模型。
- `search` 只做发现，`fetch` 读取原文；模型必须基于返回证据分析，不能把 score 当作概率或事实可信度。
- 来源权重只能调整通过相关性质量门槛的候选，不能把无关文档“加权成相关”。
- 本地 Codex 验收使用 stdio；ChatGPT 连接需要其可达的 HTTPS/tunnel 和相应账户能力，不能用 loopback URL 冒充已完成验收。

## 完成定义

满足 [ROADMAP.md](ROADMAP.md) 的当前扩展阶段退出条件，并形成以下证据：

- 后端、前端、契约和 MCP transport 测试通过；
- 同一 query 在策略修改前后的排序变化可复现；
- 文档更新保留历史版本，citation 可回到正确版本、页码和字符范围；
- Codex MCP 完成至少一组 `search → fetch → 带引用分析`；
- ChatGPT 连接在具备开发者模式及安全可达性后完成同一组验收，未到位前明确标为外部阻塞而非伪造成功；
- 版本迭代、已知限制、token 基线和规模升级触发器均有记录。
