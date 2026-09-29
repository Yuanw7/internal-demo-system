# Interface Contracts

## 来源与状态

本目录最初归档第一部分同事于 2026-09-22 交付的 `MCP架构与接口.zip`。API 1.1.0 是当前机器契约；1.0.0 已归档，本地 `backend/` 必须继续通过 path/schema 覆盖测试。未来契约升级仍必须归档旧版本和差异。

| 文件 | 角色 | 导入时 SHA-256 |
|---|---|---|
| `openapi.json` | 当前机器可读 API，版本 1.1.0 | `6d211096ec1b6a4ca4cb4288a23764e10970533fa794fee2d0b98dbb8d1a89ee` |
| `archive/openapi-1.0.0.json` | 监控 API 变更前的完整契约归档 | `05f0d35833bf5df0089f6e5cfc1f5339614aa77776d994b1aee6252ad85ed351` |
| `examples.json` | 虚构联调 fixture 与行为样例 | `a8691a7e2471c20241a11b49148653eb8bf0c09da3e6c57586087b82d54199c9` |
| `../upstream/MCP_ARCHITECTURE.md` | 第一部分架构与协作语义 | `157c171920cfe33651286b81779a299f8716c33d46d308d860886a19fb7e3cd2` |
| `../upstream/DASHBOARD_HANDOFF.md` | 上游启动和 Dashboard 联调说明 | `40f297aeef673618b7b0263ce86167ec827918c76e66c3458c759542e7d95249` |

## 优先级

发生冲突时按以下顺序处理：

1. `openapi.json` 决定字段、类型、状态码和认证声明。
2. `examples.json` 提供已知 fixture，不扩展 schema。
3. `docs/ARCHITECTURE.md` 解释本地 Hub、HTTP、MCP 与 Dashboard 的统一语义。
4. `docs/upstream/` 保留历史交付背景，不再决定当前 ownership。

如果机器契约与叙述语义冲突，停止实现相关功能并向第一部分确认，不自行猜测。

## 当前关键契约

- API prefix：`/api`
- API version：`1.1.0`
- 认证：HTTP Bearer；读与管理权限分离
- Policy 更新：`expected_version` 乐观锁
- 标准 MCP：`search`、`fetch`
- 高级 MCP：`search_documents`
- Ingestion monitoring：summary、items、item detail、admin retry；不暴露给 MCP
- JSON：`snake_case`，多数模型拒绝未知字段

## 更新流程

产生新的正式接口版本时：

1. 保留新包来源和版本说明。
2. 归档旧契约，导出完整新 OpenAPI，不手工拼接局部字段。
3. 运行 `npm test`。
4. 比较 path、schema、required、error code 和认证变化。
5. 更新本文件 hash、`docs/ARCHITECTURE.md`、客户端类型和相关测试。
6. 在 `ROADMAP.md` 或阶段报告记录迁移影响。

禁止为了让前端先跑而直接修改归档的 `openapi.json`。需要新能力时提交接口变更提案。

当前待确认提案：[`proposals/001-real-corpus-retrieval.md`](proposals/001-real-corpus-retrieval.md)，覆盖真实语料精确重复折叠、source/membership 重构和 `fetch_passage`；确认前不改变 ranking 或 MCP schema。

已确认且不改变契约的验证：[`proposals/002-information-source-ranking-v0.md`](proposals/002-information-source-ranking-v0.md)。它只用虚构目录把唯一主信息源映射到现有 `source_id/source_weights`，不增加字段或工具。

已确认且不改变契约的 V1：[`proposals/003-information-source-ranking-v1.md`](proposals/003-information-source-ranking-v1.md)。它增加内部数据库表和虚构邮件批次，但 Dashboard/MCP 继续使用 API 1.0.0 的 `sources`、Policy 和 SearchResponse。

已确认并开始实施的监控契约：[`proposals/004-ingestion-monitoring.md`](proposals/004-ingestion-monitoring.md)。它将 HTTP API 升至 1.1.0，新增自动入库 summary、item 列表/详情和乐观锁 retry；既有检索 DTO 与三个只读 MCP tools 不变。
