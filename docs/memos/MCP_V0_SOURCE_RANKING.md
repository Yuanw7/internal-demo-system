# MCP V0：信息源 Ranking 本地验证

日期：2026-09-28

## 结论

V0 已在虚构数据上跑通“来源目录 → alias 解析 → 唯一主来源 → 现有 Policy source weight → 下一次检索重排”。它复用 Retrieval Hub 的唯一服务端排序，没有新增 MCP tools，也没有连接邮箱。

## 已实现

- `source_rankings_v0.json`：版本化 Priority 1–4、默认权重、来源类型、角色顺序和显式 alias；
- `source_ranking.py`：严格配置校验、Unicode/大小写规范化、matched/ambiguous/unmatched 解析、主来源选择和 Policy 权重生成；
- 四组自动测试：alias/角色优先级、歧义与未匹配、Policy v2→v3 重排、无关文档不被来源权重召回，以及 MCP `search_documents` 使用下一次 Policy snapshot；
- 独立临时目录验收脚本，不读取或修改仓库运行数据库。
- `source-ranking-demo` CLI 可在独立数据目录幂等创建两篇虚构证据和完整 Priority 1–4 来源，不覆盖当前 Hub。

初始权重仅为验证值：Priority 1=`1.35`、Priority 2=`1.15`、Priority 3=`1.0`、Priority 4=`0.8`。这些值不是投资结论，未来必须用固定查询和分析师 relevance labels 校准。

## V0 刻意不做

- 不复制用户截图的真实信息源名单；
- 不连接真实邮箱或真实账户；
- 不把信息源、发布机构、分发人和 ingestion channel 多重相乘；
- 不自动 fuzzy match 同名人员；
- 不新增邮件全量批次工具；
- 不修改 OpenAPI/MCP schema；
- 不在 Dashboard 或 Skill 中重新计算 score。

## 运行结果

```json
{
  "catalog_version": "information-source-ranking-v0",
  "resolved_primary_source": "fixture_orion_lee",
  "preferred_policy_version": 2,
  "preferred_first": "fixture_orion_lee",
  "inverted_policy_version": 3,
  "inverted_first": "fixture_public_news",
  "mcp_contract_changed": false,
  "real_content_processed": false
}
```

创建独立可运行数据库：

```bash
backend/.venv/bin/research-hub \
  --data-dir backend/data/source-ranking-v0 \
  source-ranking-demo
```

## V1 状态

V1 虚构本地实现已完成，见 [`MCP_V1_EMAIL_SOURCE_RANKING.md`](MCP_V1_EMAIL_SOURCE_RANKING.md)。真实来源目录和真实邮箱仍需单独授权。

## 升级条件

V1 已建立虚构的持久化模型。后续真实接入应继续将 `information_source`、`publisher`、`email_sender` 和 `ingestion_channel` 分开，并补充 alias 人工确认队列与受控账户同步。

在邮箱日报必须通过 MCP 证明三个文件夹全量覆盖前，需要另行设计只读 `list_email_batch` 或等价确定性枚举接口；`search_documents` 的 Top-K 不能替代完整扫描。
