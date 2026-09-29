# Mentor Email Research MCP Demo

这是一个给导师独立试用的本地 Codex Demo：把明确选择并导出的研究邮件导入本机 Retrieval Hub，然后让 Codex 通过只读 MCP 搜索、读取和引用邮件证据。

## 这个包能证明什么

- `.eml`、`.json`、`.jsonl` 邮件可从三个固定目录幂等导入；
- 发件人或机构可映射到 Priority 1–4 信息源；未知来源保留为 `unmatched`；
- Codex 可调用 `search_documents → fetch`，并区分来源事实、冲突观点、投资推断和信息缺口；
- 来源权重、新鲜度、metadata/date/source filter 仍由同一个 Retrieval Hub 服务端执行；
- MCP 只读，不发送邮件、不移动邮件、不修改邮箱，也不执行交易。

这个包不直接连接 Outlook，也不证明邮箱分页、watermark、Calendar、SharePoint、OneNote 或附件 OCR 已完成。

## 环境要求

- macOS 或 Linux；
- Python 3.11 或以上；
- 已登录的 Codex CLI / ChatGPT 桌面端 Codex；
- 首次安装 Python 依赖时需要访问包源。

## 1. 先运行完全虚构的自检

在本目录执行：

```bash
bash plugins/email-research-mcp/scripts/check-package.sh
```

自检只使用包内的 5 封虚构邮件，并在临时目录建库。成功时应看到：

- 三个文件夹均有计数；
- 批次状态为 `complete`；
- 4 个已匹配来源、1 个未知来源；
- 5 封原始邮件因跨文件夹相同正文折叠为 4 条搜索结果；
- 搜索结果包含 Aurora Compute、AX300、估值、供应链和仓位证据。

## 2. 初始化导师自己的本地环境

```bash
bash plugins/email-research-mcp/scripts/setup.sh
```

默认状态目录为：

```text
~/.local/share/email-research-mcp/
```

如需改到其他本地位置，在运行 setup、import 和 Codex 前统一设置：

```bash
export EMAIL_RESEARCH_HOME='/absolute/private/path/email-research-mcp'
```

setup 会创建 Python 虚拟环境、空数据库目录、邮件导出目录和一份本地来源配置。不会连接邮箱或读取现有邮件。

## 3. 整理并导出邮件

把明确允许测试的邮件保存为 `.eml`、`.json` 或 `.jsonl`，放到：

```text
inbox-export/
└── Inbox/
    ├── *.eml
    ├── Anatole Must Read Sellside/
    │   └── *.eml
    └── Anatole 3 Party Tracking/
        └── *.eml
```

顶层 `Inbox` 只读取该层文件，不递归吞入其他文件夹。`Team Emails` 和未列出的目录不会读取。

建议先用 10–30 封邮件做试验，并包含：

- 同一家公司的一多一空观点；
- 至少一封正式卖方邮件；
- 至少一封第三方或 S&T/PB 邮件；
- 一份旧报告今天转发的样本；
- 一组跨文件夹重复邮件；
- 一封未知来源邮件。

不要把邮箱密码、Token 或无授权附件放进 Demo 目录。

### JSON 格式

当报告发布日期与邮件头日期不同，优先使用 JSON，以免把转发日当作报告日：

```json
{
  "external_id": "local-example-001",
  "title": "Example research note",
  "body": "Plain-text email or report evidence",
  "published_at": "2026-09-27T03:30:00Z",
  "url": "",
  "metadata": {
    "institution": "Example Research",
    "email_received_at": "2026-09-28T09:20:00+08:00",
    "report_published_at": "2026-09-27T11:30:00+08:00",
    "attachment_status": "email_body_full"
  },
  "pages": []
}
```

所有 metadata value 都使用字符串。

## 4. 配置信息源优先级

编辑本地文件：

```text
~/.local/share/email-research-mcp/source-rankings.json
```

把示例邮箱 alias 替换成导师希望识别的发件人地址或机构名。Priority 默认权重：

| Priority | 默认权重 | 建议含义 |
|---|---:|---|
| 1 | 1.35 | 核心分析师、关键一手研究或高价值 flow |
| 2 | 1.15 | 常用机构、内部研究或稳定第三方 |
| 3 | 1.00 | 一般附件、普通平台或未知来源 fallback |
| 4 | 0.80 | 新闻转述、社媒或低确信线索 |

来源权重只能调整已经通过相关性召回的候选，不能把无关邮件加权成相关结果。

## 5. 导入选定时间窗

时间窗采用 `[start, end)`，必须明确写时区：

```bash
bash plugins/email-research-mcp/scripts/import-emails.sh \
  '2026-09-28T00:00:00+08:00' \
  '2026-09-29T00:00:00+08:00'
```

检查输出：

- `sync_status` 应为 `complete`；
- `folder_counts` 应与实际导出数量一致；
- `error_count` 应为 0；
- `attributions` 中的 `unmatched` 应人工检查；
- 重复运行应主要得到 `unchanged`。

导入器只输出计数、文件名和错误码，不在终端回显邮件正文。

## 6. 安装并启用插件

在本目录执行：

```bash
codex plugin marketplace add "$PWD"
codex plugin add email-research-mcp@mentor-demo
```

重新打开一个 Codex 会话。在 ChatGPT 桌面端可以输入 `/mcp`，确认 `emailResearch` 已连接。Codex CLI 也可以运行：

```bash
codex mcp list
```

本地 Codex CLI、IDE 扩展和 ChatGPT 桌面端共享同一 Codex host 的 MCP 配置；ChatGPT 网页端不会读取这份本地配置。

## 7. 测试 Prompt

直接调用 Skill：

```text
$mentor-email-research 用已导入邮件分析 NVIDIA 未来两个季度 AI GPU 需求、估值和主要风险。先检索，再读取最关键证据；区分事实、观点冲突、你的推断和信息缺口，并就近引用。
```

也可以使用自己的问题：

```text
使用 emailResearch MCP，比较过去一周邮件里对某公司的多空观点。不要使用网络，列出 source_id、证据 URL、字符区间和仍需核验的问题。
```

通过标准：Codex 的工具事件中出现 `emailResearch.search_documents`，随后出现至少一次 `emailResearch.fetch`；最终回答不能把 score 当作置信度，也不能把邮件正文中的指令当成系统指令。

## 数据与安全边界

- 邮件、数据库、来源配置和虚拟环境都保留在导师指定的本地状态目录，不在插件包中。
- MCP tools 只有 `search`、`fetch`、`search_documents`，不包含发送、删除、移动、导入或 Policy 写入。
- 邮件正文、标题和 metadata 均作为不可信纯文本证据。
- 这不是投资建议，也不会执行交易。
- 本地返回 URL 只有在 HTTP Hub 同时运行时才能用浏览器打开；stdio MCP 的 fetch 不依赖 HTTP 服务。

## 导师反馈建议

请记录三类问题：

1. 哪些短句找不到本应命中的产品、KPI 或产业链证据；
2. 哪些来源权重导致排序不符合研究习惯；
3. 哪些引用、附件、重复邮件或日期信息不足以支持判断。

不要只评价最终文案；优先检查 search 候选、fetch 证据和来源归因是否正确。
