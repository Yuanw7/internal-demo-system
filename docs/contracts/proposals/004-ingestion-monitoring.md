# Proposal 004：自动入库状态与监控 API

状态：已确认并开始实施
日期：2026-09-29
目标版本：OpenAPI 1.1.0

## 背景

OpenAPI 1.0.0 只暴露资料库、检索、文档和 Policy，无法让 Dashboard 判断自动监听中的数据是待处理、处理中、已处理、失败还是重试中。现有 `email_sync_runs/items` 只描述一次邮件导入覆盖，不能承担通用 worker queue、lease、attempt、dead letter 和向量发布状态。

## 已确认语义

- 首期 Connector 只有 Capital IQ 本地目录与 Outlook；真实 Outlook 账号仍需单独授权。
- `processed` 必须表示 FTS 和 dense-vector generation 均已发布。
- 文档更新和源端删除均保留不可变历史版本。
- Dashboard 只展示服务端状态，不在客户端推导状态。
- MCP 工具不变，继续只读。

## 1.1.0 新增接口

| Method | Path | 权限 | 作用 |
|---|---|---|---|
| GET | `/api/ingestion/summary` | Read | 五态、向量积压、死信和最老积压 |
| GET | `/api/ingestion/items` | Read | 按状态、Connector、stage 筛选并 cursor 分页 |
| GET | `/api/ingestion/items/{item_id}` | Read | item、attempt 和状态事件详情 |
| POST | `/api/ingestion/items/{item_id}/retry` | Admin | 使用 `expected_state_version` 人工重试 |

批次查询、批次重跑、Connector scan 和 SSE 保留为后续 1.2 提案内容，不在 1.1.0 中提前暴露不稳定字段。

## 兼容性

- 1.0.0 的所有路径、请求和响应模型保持不变。
- 仅新增 schema/path，并将 API info version 升至 1.1.0。
- HTTP MCP 的 `/mcp` 和三个 MCP tool schema 不改变。
- 1.0.0 已归档到 `docs/contracts/archive/openapi-1.0.0.json`。

## 错误与并发

- 监控读取使用 Read/Admin Token。
- retry 仅接受 Admin Token。
- retry 必须携带 `expected_state_version`；版本不一致返回 `409 ingestion_state_version_conflict`。
- 已处理或处理中 item 返回 `422 ingestion_item_not_retryable`。
- 正文不通过监控接口返回；文件名或邮件主题按纯文本处理。
