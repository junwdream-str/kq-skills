# 群与机器人台账（机器数据源）

本文件由 WorkBuddy 读写，不由人工维护。下方 JSON 代码块是唯一事实源，修改时只改代码块内容，保持结构与字段完整。

字段契约：

- `id`：稳定编号，形如 R1、R2，一经分配不再变更
- `alias`：群的别名数组，用于点名解析
- `groupName`：群名称；为空表示待用户补全
- `openConversationId`：群 ID，`bot` 身份必填，`webhook` 留 null
- `robotName`：机器人名称，可为空
- `identity`：`webhook` 或 `bot`
- `robotCode`：`bot` 身份的机器人 Code
- `webhookToken`：`webhook` 身份的凭证，敏感字段，禁止在对话中回显
- `security.sign`：是否启用加签；`true` 时当前通道不可用
- `security.keywords`：自定义关键词列表，非空时正文必须包含其一
- `security.ipWhitelist`：IP 白名单，空数组表示未配置
- `status`：`verified` 已验证、`unverified` 未验证、`invalid` 已失效
- `lastErrcode`：最近一次发送的错误码，用于快速判断通道健康度

```json
{
  "version": 1,
  "updatedAt": "2026-09-10T09:46:10+08:00",
  "defaults": {
    "identity": "webhook",
    "msgType": "markdown",
    "confirmBeforeSend": true
  },
  "targets": [
    {
      "id": "R1",
      "alias": [
        "应用测试",
        "应用测试群"
      ],
      "groupName": "应用测试",
      "openConversationId": null,
      "robotName": null,
      "identity": "webhook",
      "robotCode": null,
      "webhookToken": "63ddbf413b7bfda209e9fa9086f36cb74b71d1d86086e439c7b4f9ed7d8c3646",
      "security": {
        "sign": false,
        "keywords": [],
        "ipWhitelist": []
      },
      "status": "verified",
      "verifiedAt": "2026-09-10T09:34:00+08:00",
      "lastErrcode": "0",
      "note": "群名称由用户于 2026-09-10 补充；webhook 目标群由 token 决定，发送时无需 openConversationId"
    }
  ],
  "sendLog": [
    {
      "time": "2026-09-10 09:34",
      "targetId": "R1",
      "groupName": "应用测试",
      "identity": "webhook",
      "title": "this a test",
      "at": null,
      "errcode": "0",
      "errmsg": "ok",
      "operator": "王骏"
    },
    {
      "time": "2026-09-10 09:46",
      "targetId": "R1",
      "groupName": "应用测试",
      "identity": "webhook",
      "title": "WorkBuddy",
      "at": null,
      "errcode": "0",
      "errmsg": "ok",
      "operator": "王骏"
    }
  ]
}
```
