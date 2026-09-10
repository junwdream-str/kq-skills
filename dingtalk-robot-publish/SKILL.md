---
name: dingtalk-robot-publish
description: 向钉钉群发布机器人消息。当用户要求"发到钉钉群/给某群发通知/用机器人推送/向 XX 群发消息/发告警/发日报到群"，或提到群自定义机器人 Webhook、robotCode、群消息推送时使用。本 skill 维护一份群与机器人的映射台账 registry.md，按群名解析目标，缺凭证时向用户索取并自动回填。
version: 1
---

# 钉钉群机器人发布

通过 dws 的 `chat` 服务向指定钉钉群发送消息。核心资产是 `registry.md`，它保存群、机器人、凭证的映射关系，是本 skill 的唯一数据源。

## 强制性规则

- 所有发送都是写入操作，确认级别 `user_required`。必须先 `--dry-run`，向用户展示摘要，用户明确确认后才加 `--yes` 执行。禁止静默发送。
- 禁止在对话回复中回显完整 token。需要指代时只显示前 8 位加省略号，例如 `63ddbf41...`。
- 不猜测 token、robotCode、openConversationId。缺失即停止并询问用户。
- 每次发送后必须把结果回填到 `registry.md` 的 `sendLog` 与目标的 `lastErrcode`。

## 解析目标群

读取 `registry.md` 中的 JSON，在 `targets` 数组内按顺序匹配：

1. `id` 精确匹配（如 R1）
2. `alias` 数组内任一元素精确匹配
3. `groupName` 精确匹配，再退化为包含匹配

匹配统一忽略大小写与首尾空格。多个命中时列出候选让用户选择，禁止自行取第一项。

## 命中后的发送流程

1. 取出该 target 的 `identity`、`webhookToken` 或 `robotCode`、`openConversationId`。
2. 若 `groupName` 为空，先请用户给这个群起一个名字，写回 `groupName` 并追加到 `alias`，再继续。
3. 构造命令并 `--dry-run` 核对参数。
4. 向用户展示摘要：目标群、身份、标题、正文、是否艾特。
5. 用户确认后加 `--yes` 执行。
6. 把时间、标题、errcode、errmsg 写入 `sendLog`，更新该 target 的 `lastErrcode`、`verifiedAt`、`status`。

## 未命中时的索取流程

不要编造，不要跳过。按以下话术向用户索要，拿到后立即写入 `targets` 新条目并回复"已登记"：

- 群名称（用于以后点名，必填）
- 身份类型：`webhook` 或 `bot`，默认为 `webhook`
- 凭证：`webhook` 需要 Webhook token（或完整 URL，从中提取 `access_token` 参数）；`bot` 需要 robotCode 与群 openConversationId
- 可选：别名、机器人名称、安全设置（加签 / 关键词 / IP 白名单）

新条目写入规则：`id` 取 `R` 加当前最大序号加一；`status` 先置为 `unverified`，首次发送成功后再改为 `verified`；`updatedAt` 同步为当前时间。

写入前先把要新增的条目展示给用户确认，确认后再落盘。

## 命令模板

webhook 身份，目标群由 token 决定：

```bash
dws chat +messages-send-by-webhook --token "<webhookToken>" --title "标题" --content "Markdown 正文" --yes --format json
```

bot 身份，需指定机器人与群：

```bash
dws chat +messages-send-by-bot --robot-code "<robotCode>" --group "<openConversationId>" --title "标题" --content "Markdown 正文" --yes --format json
```

bot 批量发多个群，最多 100 个，逐群返回 ledger：

```bash
dws chat +messages-send --as bot --robot-code "<robotCode>" --groups "<id1>,<id2>" --text "正文" --yes --format json
```

艾特参数：`--at-all`、`--at-users <userId,userId>`、`--at-mobiles <手机号>`。

## 辅助查询

```bash
dws chat +chat-search --query "群名关键词" --format json   # 取 openConversationId
dws chat +bot-search --name "机器人名" --format json        # 取自己创建的机器人 robotCode
dws chat +bot-find --query "关键词" --limit 10 --format json # 搜索全部可用机器人
```

## 失败处理

`errcode` 非 0 时按 `errmsg` 判断，保留原始错误码上报用户，禁止自行改参数重试：

- 提示签名或 sign 相关：机器人启用了加签，当前 webhook 通道不支持传 secret，需用户改用关键词或 IP 白名单模式
- 提示关键词：正文必须包含该机器人配置的自定义关键词，请用户提供关键词后重写正文
- 提示 IP 不在白名单：需把出口 IP 加入白名单
- 提示 token 无效或过期：请用户重新提供 token，覆盖写入并重新验证

## 已知限制

- `webhook` 与 `bot` 身份不支持富媒体，文件与图片发送只有 `user` 身份可用
- `bot` 批量发送单次上限 100 个群
- webhook 的目标群由 token 决定，无法在发送时切换；需要按群名精确指定时改用 `bot` 身份
