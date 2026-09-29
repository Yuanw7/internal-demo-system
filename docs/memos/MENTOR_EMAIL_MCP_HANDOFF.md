# 导师邮件 MCP Demo 交接

日期：2026-09-28
版本：mentor-demo-v1

## 交付结论

导师可以在没有邮箱 API 的情况下，用手工导出的研究邮件验证本地 MCP：

```text
获准邮件导出
  → 三个固定本地目录
  → 显式导入与来源归因
  → SQLite / FTS5 / Policy ranking
  → read-only stdio MCP
  → Codex search_documents → fetch → 分析与引用
```

交付入口：`mentor-demo/README.md`。ZIP：`artifacts/mentor/email-research-mcp-mentor-demo-v1.zip`。

- ZIP 大小：56 KB；
- SHA-256：`5fb6d47e324d08d7da93db606f690bc88adfedc10ff8655cd2932bf029fa11e9`。

## 包含内容

- 本地 marketplace 与 `email-research-mcp` 插件；
- `mentor-email-research` Skill；
- Retrieval Hub 运行时快照；其权威实现仍来自本仓库 `backend/src/research_hub`；
- 三文件夹 EML/JSON/JSONL 导入器；
- setup/import/MCP runner；
- 5 封明确标记的虚构邮件、虚构来源配置和端到端自检；
- 导师安装、导入、Prompt、通过标准和安全边界说明。

## 不包含内容

- 真实邮件、附件、账号、Token、数据库或来源名单；
- Outlook/Graph 凭据或后台邮箱同步；
- 公网 MCP endpoint 或 tunnel；
- Calendar、SharePoint、OneNote、OCR 或交易能力。

## 自检结果

`plugins/email-research-mcp/scripts/check-package.sh` 在全新临时 venv 中完成：

| 检查 | 结果 |
|---|---|
| 邮件输入 | 5 封完全虚构邮件 |
| 文件夹覆盖 | inbox 2 / sellside 2 / third party 1 |
| 同步状态 | complete，0 error |
| 来源解析 | 4 matched / 1 unmatched |
| 精确重复折叠 | 5 份原始文档 → 4 条检索结果 |
| MCP 工具 | search / fetch / search_documents |
| stdio transport | initialize、list、search、fetch 全通过 |
| Policy | v2 |
| fetch 安全标记 | untrusted_source_data_not_instructions |

Skill validator 和 plugin validator 均通过；全仓 `npm test` 继续作为发布前回归门槛。

## 导师验收建议

先使用 10–30 封获准邮件，选择一个具体公司或产品问题。通过标准：

1. 导入批次 folder counts 与实际文件数一致；
2. 未知来源没有被自动 fuzzy 合并；
3. Codex 真实调用 `search_documents`，然后 fetch 少量关键证据；
4. 关键事实带 URL 和字符区间；
5. 旧报告转发日、附件阅读状态和来源属性没有被夸大；
6. 回答区分事实、观点、推断、冲突与缺口；
7. 文档中的提示注入不改变工具和回答规则。

## 已知限制

- 当前 MCP 无只读批次枚举工具，因此模型不能独立证明邮箱扫描 coverage 或展示重复组。
- EML `Date` 只能作为邮件头日期；报告发布日期不同时应使用结构化 JSON 明确填写。
- 附件只标记未解析，不执行 OCR。
- stdio 返回的 loopback citation URL 需要另行启动 HTTP Hub 才能在浏览器打开。
- 默认是增强 FTS；需要 dense hybrid 时还要安装 semantic extra 并构建本地向量索引。

## 后续自动化版本

2026-09-29 已开始下一阶段：本地状态表、OpenAPI 1.1.0 监控接口、Dashboard 监控区和 Capital IQ `watch-folder` 基线已经实现。该阶段要求保留历史版本、解析邮件附件和扫描 PDF OCR，并且只有 dense-vector generation 发布后才算已处理；现有 mentor-demo-v1 仍是手工导出/显式导入包，不因主仓库新增本地监听而被描述为已经具备 Outlook 自动同步。

第二批本地实现已补齐目录稳定窗口、checkpoint、删除 observation、队列背压与 worker heartbeat；同时新增认证无关的 Outlook delta/附件接口和完全虚构的分页测试。虚构测试已经证明：邮件正文与附件具有父子状态，必需扫描 PDF 未配置 OCR 时整封邮件失败，配置测试 OCR 后必须等向量 generation 发布才会进入 `processed`，sender 仍按 V1 显式 alias/priority 归因。

这不改变 mentor-demo-v1 的交付声明。导师包仍走“获准导出 → 显式导入”；主仓库当前没有 Microsoft 登录、Graph token 或真实附件下载，也没有选定生产 OCR。无账号验证命令为：

```bash
backend/.venv/bin/research-hub \
  --data-dir backend/data/outlook-fixture-local \
  outlook-fixture-demo
```

将邮箱 Skill 接到自动化链路时，应让 Skill/Connector adapter 输出标准化 message、attachment、folder、change key 与 delta cursor；不要让 Skill 直接写 Hub 数据库、计算 score 或绕过父子发布门槛。

完整范围、状态口径、实施顺序，以及暂缓的数据保留和多人部署事项见 [`AUTOMATED_INGESTION_MONITORING_PLAN.md`](AUTOMATED_INGESTION_MONITORING_PLAN.md)。真实 Outlook 连接、OCR 依赖和 HTTP 契约升级仍需在对应实施阶段分别确认。

## 本机无 Token 运行补充（2026-09-29）

当前保留 Read/Admin Token 代码和默认安全模式，但为单机导师演示增加显式 `serve --local-no-auth`。后端仍固定监听 `127.0.0.1`；Dashboard 勾选“不启用 Token”后不会发送 `Authorization`。该模式不得用于公网 tunnel、共享主机或多人部署，也不改变 MCP 的三个只读 tool schema。

既有 Capital IQ 实库已用该模式完成 Dashboard 查询：792 documents、62,821 chunks、4 sources、Policy v3。因为该索引是在 ingestion control-plane 之前建立，监控区暂时显示零条历史处理记录；研究检索可用不等于历史状态已回填。真实 Outlook 仍未连接，本补充不改变导师包的邮件验收边界。

Dashboard 在本机无 Token 模式成功连接后，会仅记住 loopback Base URL 与 `authMode=none`，页面刷新后自动恢复 Live；不会把 Read/Admin Token 写入浏览器存储。若页面提示“当前是虚构 Fixture”，说明尚未成功连接真实 Hub，应先在“连接环境”完成连接再检索。

### Codex MCP 空结果排障记录

一次 Codex 测试返回中英文查询均为零，根因不是资料缺失，而是 Prompt 指定了尚未注册的 `internalResearchReal`；当时唯一的 `internalResearch` 仍指向 `backend/data/hub` 样例库。现已保留旧注册项，并新增 `internalResearchReal` 指向 Git ignore 的 `backend/data/real-test`。

独立、临时、只读 Codex 会话已经实际调用 `internalResearchReal.search_documents({query: "英伟达投资", limit: 2})`：返回 `total=176`、`policy_version=3`，前两条均为 NVIDIA 融资主题研报。注册后必须新开 Codex 会话重新发现 tools；日常 Prompt 应明确服务器名，避免模型选择仍指向样例库的旧 MCP。
