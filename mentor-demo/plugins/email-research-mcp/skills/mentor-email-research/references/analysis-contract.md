# Email research analysis contract

## Source hierarchy

Use this hierarchy as evidence quality context, not as an automatic relevance override:

1. Company, regulator, or government primary material.
2. Actually inspected internal model or thesis note.
3. Formal sell-side research.
4. Professional third-party data.
5. S&T, PB, lending, or flow data.
6. Expert commentary.
7. Sales relay, social media, or unverified rumor.
8. Model inference or scenario analysis.

The saved Retrieval Policy controls ranking. Do not re-sort MCP results locally.

## Minimum answer

- State the query scope and `policy_version` when returned.
- Cite every material fact beside the claim.
- Explain whether opposing views are true conflicts or different periods/definitions.
- Label the model's own conclusion as inference.
- End with missing evidence and concrete follow-up checks.
- State that the result is based on imported email evidence and is not investment advice.

## Useful prompts

- `用已导入邮件分析 Aurora Compute 的 AX300 需求、估值和供应链风险。`
- `比较过去两周邮件里对某公司的多空观点，并指出口径差异。`
- `找出最影响某公司未来两个季度收入的三条证据，并列出仍需核验的问题。`

## Not supported by this package

- Direct Outlook access, mailbox writes, email sending, or folder modification.
- Proof of complete mailbox pagination or watermark continuity.
- Automatic attachment OCR.
- Calendar, SharePoint, or OneNote reconciliation.
- Trading or portfolio actions.
