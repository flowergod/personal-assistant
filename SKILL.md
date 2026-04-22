# Personal 个人助理 - 飞书表格 + iCloud 日历双向同步

## 功能

Personal Assistant 是一套个人任务+日历管理系统：
- **单一数据源**：所有任务存在飞书多维表格
- **双向同步**：自动同步到对应 iCloud 日历，手机随时可以查看提醒
- **三级结构**：项目 → 子项目 → 具体任务，保持清晰
- **自然语言解析**：支持用自然语言直接添加任务

## 目录结构

```
personal-assistant/
├── SKILL.md              # 本文档
├── api.py                 # FastAPI 接口服务
├── scripts/
│   ├── sync_single_to_icloud.py    # 单个飞书记录同步到 iCloud 日历
│   └── batch_sync_unsynced.py     # 批量同步所有未同步记录
├── log/                       # 操作日志存放目录
└── memory.py                # 操作日志和统计
```

## 配置

### 飞书多维表格

需要提前在飞书创建多维表格，包含以下字段：

| 字段名 | 类型 | 必填 | 说明 |
|--------|------|------|------|
| `序号` | 自动编号 | 是 | |
| `任务名称` | 文本 | 是 | |
| `项目` | 文本 |  | 一级项目 |
| `子项目` | 文本 |  | 二级子项目 |
| `分组` | 单选 | 是 | `日程表`/`工作`/`生活`/`个人`/`其他` |
| `优先级` | 单选 | 是 | `高`/`中`/`低` |
| `状态` | 单选 | 是 | `待规划`/`待执行`/`进行中`/`已完成`/`暂停` |
| `循环类型` | 单选 |  | `不循环`/`每周一`/`每周五`/`每周`/`每月`/`每年`/`不定期` |
| `日历分类` | 单选 |  | `不同步`/`个人`/`工作`/`家庭共享` → 对应 iCloud 不同日历 |
| `完成次数` | 数字 | 是 | 循环任务完成次数 |
| `计划日期` | 日期 |  | |
| `开始时间` | 日期时间 |  | UTC 毫秒时间戳 |
| `结束时间` | 日期时间 |  | UTC 毫秒时间戳 |
| `iCloud事件ID` | 文本 |  | 同步后保存 UID |
| `备注` | 文本 |  | 地点/备注信息 |

### 环境变量

```bash
export FEISHU_APP_TOKEN="YmMcb4PUlaTIAmshS6EcFqPenff"
export FEISHU_TABLE_ID="tbllwg2t4sEJ64i1"
```

### iCloud 日历配置

`~/.vdirsyncer/config` 需要配置好三个 CalDAV 配对对应三个日历：

| 飞书 `日历分类` | vdirsyncer pair | 本地目录 |
|----------------|---------------|------------|
| `个人` | `icloud_personal` | `~/.../F7D25790-4368-447C-96FF-4F7FE022AE1C/F7D25790-4368-447C-96FF-4F7FE022AE1C` |
| `工作` | `icloud_work` | `~/.../D03AAE8F-D142-42CF-8FF2-BA7AB2E83092/D03AAE8F-D142-42CF-8FF2-BA7AB2E83092` |
| `家庭共享` | `icloud_family_new` | `~/.../family-new/family-new` |

已经配置完成。

## 使用方法

### 单个同步

```bash
python /app/skills/personal-assistant/scripts/sync_single_to_icloud.py \
  --record-id [FEISHU_RECORD_ID] \
  --title "事件标题" \
  --start-cst "2026-04-24 09:00" \
  --end-cst "2026-04-24 17:00" \
  --category work \
  --location "上海浦东丽思卡尔顿酒店"
```

### 批量同步所有未同步记录

批量同步满足以下条件的记录：
1. 有 `开始时间` + `结束时间`
2. `日历分类` 不是 `不同步`
3. `iCloud事件ID` 为空（尚未同步）
4. `状态` 不是 `已完成`

```bash
python /app/skills/personal-assistant/scripts/batch_sync_unsynced.py
```

### 任务状态规则

| 状态 | 说明 | 同步 |
|------|------|------|
| `待规划` | 任务已创建，但尚未确定时间，不需要同步日历 | ❌ |
| `待执行` | 已有明确计划，需要同步日历 | ✅ |
| `进行中` | 长期项目，不需要日历事件 | ❌ |
| `已完成` | 任务已完成，从日历删除 | ❌ （需要手动删除） |
| `暂停` | 任务暂停推迟 | ❌ |

## 同步规则总结

### 飞书 → iCloud 方向

1. 飞书表格中填写任务，给出开始/结束时间，选择日历分类
2. 保持状态为 `待执行`
3. 运行批量同步脚本：
   - 自动生成符合 iOS 格式的 `.ics` 文件（包含完整时区定义、默认15分钟提醒）
   - 放到正确的日历目录
   - 更新飞书记录写入 `iCloud事件ID` = UID
   - 执行 `vdirsyncer sync` 推送到 iCloud

### iCloud → 飞书 方向

1. 在 iPhone 日历 app 中修改/新增/删除
2. 执行 `vdirsyncer sync` 拉取到本地
3. 下一步需要：扫描本地变化，更新飞书表格（功能待完成）

## .ics 文件格式要求（兼容 iCloud）

必须满足：
1. `.ics` 文件放在日历 UUID 子目录下面，和 iOS 同步下来的文件放在一起
2. 包含完整 `VTIMEZONE` 时区定义（Asia/Shanghai），和 iOS 生成的保持一致
3. `DTSTART/DTEND` 必须带 `TZID=Asia/Shanghai`，存储**中国标准时间**，不存 UTC
4. 包含 `CREATED`/`DTSTAMP`/`LAST-MODIFIED`/`SEQUENCE` 这些字段
5. 默认添加 15 分钟提醒 `VALARM`
6. `LOCATION` 存放地点信息

**这些都已经在脚本中自动处理好了，只需要正确填写飞书表格就行。**

## 已知问题

- 循环任务（每周/每月重复）目前不自动同步，需要手动在日历创建
- 已完成任务不会自动从日历删除，需要手动删除

## 日期时间戳规则

- 飞书表格存储 **UTC 毫秒时间戳**（13位数字）
- 脚本自动转换为中国标准时间写入 .ics
- iCloud 日历正确显示本地时间

