# 提案 001：真实语料重复折叠、来源模型与 passage fetch

状态：A 已随 2026-09-24 混合检索精度调整实施；B/C 仍等待单独确认，MCP schema 未变。

日期：2026-09-24

## 触发证据

- 全量 802 份 PDF 中 792 份成功入库。
- 当前文档包含 154 个完全相同正文 SHA 组，共占用 158 个额外 document slot。
- Top 50 中，`Nebius` 有 23 个重复结果位，`Snowflake` 有 21 个。
- 一次真实 Codex 分析因为读取多份全文消耗约 51,035 token。
- Kioxia/NBIS/SNOW 是“正文包含公司名”的集合，不是互斥发布来源；同一报告可以属于多个集合。

## A. 精确重复折叠

建议在 source/date/metadata filter 和 BM25 计算之后、最终 limit 之前，按当前 version 的 `body_sha` 折叠：

1. 每个 document 先选择最佳 chunk。
2. 相同 `body_sha` 的 document 选择最终 score 最高者。
3. 分数相同按 document ID 稳定决胜。
4. `matched_chunks` 保持原始匹配量；`total` 改为折叠后的逻辑报告数。
5. 原文、版本和 membership 不删除，`fetch` 继续读取被选中的稳定 document ID。

优点：不依赖模糊相似度，不会把修订版自动合并；来源权重仍可决定相同正文采用哪个 representation。

风险：`total` 语义变化，Dashboard 排名对比会看到候选数下降；若要返回 `alternate_sources` 或 `duplicate_group_id`，需要新增契约字段。

明确不做：不按标题、文件名或近似文本自动折叠。

## B. source 与 membership 重构

建议：

- `source` 表示发布者/券商或受控供应渠道，而不是 Kioxia/NBIS/SNOW 公司集合。
- 新增 `collections` 和 `document_collection_memberships`，保存目标公司集合、匹配规则版本和 mention strength。
- 先将文件名首段解析为候选 publisher，并人工校验映射；未校验值进入 `unknown_publisher`，不能静默归一化。
- Dashboard 的 source weight 继续作用于发布者/渠道；公司集合通过 metadata/membership filter 使用。

迁移前保留当前四个 source ID，避免无审查重写已有 Policy。

## C. 新增 `fetch_passage`

保留标准 `fetch(id)` 完整正文语义，新增只读工具：

```json
{
  "id": "document-id",
  "start": 1000,
  "end": 2200,
  "context_chars": 800
}
```

约束：

- `id` 必须来自 search；
- `0 <= start < end <= len(text)`；
- `context_chars` 默认 500、最大 2000；
- 最终返回文本最大 12,000 字符；
- 返回实际 citation、title、URL、version ID 和内容信任标记；
- 不接受文件路径，不进行新的 ranking 或 LLM 摘要。

HTTP 对应候选：`GET /api/documents/{id}/passage?start=&end=&context_chars=`。这需要正式 OpenAPI 小版本升级、TypeScript contract 重新生成和 HTTP/MCP parity 测试。

## 推荐批准顺序

1. 先批准 A：精确正文 SHA 折叠，直接消除已量化的重复结果位。
2. 再批准 C：passage fetch，降低真实分析 token。
3. B 需要 publisher 映射人工校验，单独实施和迁移。

当前实现已在最终 limit 前按 `body_sha` 保留最高 score representation，并通过测试证明来源权重仍能决定保留项；不删除任何版本或来源记录。B 的 source/membership 重构及 C 的 passage tool 尚未实施，工具 schema 和 API 契约仍保持 1.0.0。
