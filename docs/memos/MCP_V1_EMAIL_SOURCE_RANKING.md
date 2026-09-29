# MCP V1：邮件信息源持久化与批次完整性

日期：2026-09-28

## 结果

V1 已在完全虚构的数据上完成：EML/JSON 邮件解析、信息源 alias 匹配、主来源持久化、三文件夹同步批次核对、现有 Dashboard 来源列表兼容，以及 MCP `search_documents` 随下一版 Policy 重排。

## 验收结果

```json
{
  "version": "information-source-ranking-v1",
  "schema_migration": 3,
  "information_sources": 8,
  "sync_status": "complete",
  "folder_counts": {
    "inbox": 1,
    "inbox_sellside": 1,
    "inbox_third_party": 0
  },
  "attributions": ["matched", "matched"],
  "before_policy_version": 2,
  "before_first": "fixture_orion_lee",
  "after_policy_version": 3,
  "after_first": "fixture_northstar_research",
  "rerun_unchanged": 2,
  "mcp_contract_changed": false,
  "real_content_processed": false
}
```

## 运行

创建独立 V1 数据库：

```bash
backend/.venv/bin/research-hub \
  --data-dir backend/data/source-ranking-v1 \
  source-ranking-v1-demo
```

执行一次性验收：

```bash
backend/.venv/bin/python backend/scripts/check_source_ranking_v1.py
```

V1 数据目录与当前 `backend/data/hub` 分开；命令不会更改全局 Codex MCP 注册。

## 数据路径

```text
虚构 EML / JSON
  → 提取 sender/institution metadata
  → canonical/explicit alias 精确解析
  → 唯一 primary information source
  → document version attribution
  → documents/pages/chunks
  → FTS5 / dense retrieval
  → source_weights + freshness
  → HTTP / MCP
```

## Dashboard

V1 把信息源同步进现有 `sources`，所以当前 Dashboard 不需要新增客户端 ranking：它可以通过已有 `/api/sources` 展示来源，并通过 `PUT /api/policy` 修改权重。信息源类型、alias 和同步批次目前只存在后端审计表中，尚未新增 UI 面板。

## 当前限制

- 尚未连接真实 Outlook、Calendar、SharePoint 或 OneNote；
- 尚未读取附件，V1 fixture 只验证 EML 正文和 JSON 文档；
- 没有 HTTP/MCP `list_email_batch`，因此模型不能自行证明某个真实时间窗已经全量扫描；
- V1 仍使用唯一主来源，secondary attribution 尚不参与 ranking；
- alias 仅精确匹配，不自动 fuzzy match；
- 真实来源名单必须通过仓库外受控配置导入，不能直接提交截图内容。

## 下一步触发条件

接入真实邮箱前必须单独确认账户、权限、目标文件夹、watermark 存放和真实内容处理范围。若需要让 ChatGPT 独立检查批次完整性，则先升级契约并增加只读批次枚举工具。
