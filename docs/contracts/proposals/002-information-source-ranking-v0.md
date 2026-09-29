# Proposal 002 — Information-source ranking V0

状态：已确认并完成本地 V0 验证。

确认依据：用户于 2026-09-28 明确要求“先进行 mcpv0”。本提案实现的是此前说明的静态信息源 ranking V0，不连接真实邮箱或处理真实内部内容。

## 目标

在不修改 OpenAPI 1.0.0 和 MCP tool schema 的前提下，验证以下闭环：

1. 版本化目录保存 Priority 1–4、默认权重、显式别名和来源角色；
2. 一份文档只选择一个 `primary ranking source`；
3. 当前 `RetrievalPolicy.source_weights` 承载主信息源权重；
4. 权重更新后的下一次 HTTP/MCP 查询使用新 Policy version；
5. 来源权重只作用于已经被 lexical/semantic retrieval 召回的候选。

## V0 数据边界

- 配置和自动测试只包含明确标记的虚构来源与虚构正文。
- 用户截图中的真实名单只用于确认“分层来源＋匹配状态”需求，不复制进 Git。
- 不连接 Outlook、Calendar、SharePoint 或 OneNote。
- 不建立邮件线程、附件 occurrence、同步 cursor 或 ACL 表。
- 不新增写入型 MCP tool。

## 主来源选择规则

V0 使用配置声明的角色优先级。默认顺序为：分析师、报告作者、邮件发送人、机构、内部笔记、数据提供商、研究平台、新闻、社交媒体、人工上传。

解析只接受 canonical name 或人工确认 alias。不存在的名称为 `unmatched`；同一 alias 对应多个来源时为 `ambiguous`。V0 不进行可能把同名分析师错误合并的 fuzzy match。

## 契约影响

无。`search`、`fetch`、`search_documents`、SearchResponse、Policy DTO 和 API 1.0.0 均不变化。V0 将主信息源映射到现有 `source_id`，并复用现有 `source_weights` 与 `policy_version`。

未来若增加多来源归因、来源解析状态响应字段或 `list_email_batch`，必须另立契约版本和迁移提案。

## 验收

运行：

```bash
backend/.venv/bin/python backend/scripts/check_source_ranking_v0.py
```

预期：

- alias 解析得到虚构 Priority 1 主来源；
- 默认 tier weights 下 Priority 1 排第一；
- 反转 Policy 后下一次查询由另一来源排第一；
- 两次查询分别返回 Policy v2、v3；
- 输出明确 `mcp_contract_changed: false` 和 `real_content_processed: false`。
