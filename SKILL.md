---
name: personal-assistant
description: Personal life assistant with Feishu Bitable + iCloud CalDAV sync. Natural language task parsing, daily morning/evening reports, recurring task management.
metadata: {"clawdbot":{"emoji":"⚡","os":["linux"],"requires":{"bins":["vdirsyncer","khal","python3"]},"requires_skills":["feishu-bitable", "caldav-calendar"]}}
---

# Personal Life Assistant (Feishu Bitable + iCloud CalDAV)

Complete personal task + calendar management system:
- **Single source of truth**: All tasks stored in Feishu Bitable
- **Two-way sync with iCloud**: Calendar events sync to iCloud family/personal/work calendars
- **Natural language parsing**: Add tasks/events via natural language
- **Daily workflow**: Morning push today's schedule + todos; Evening confirmation for completion
- **Recurring task support**: Auto-generate next occurrence after completion

## Architecture

```
Feishu Bitable (single source) ↔ vdirsyncer/local .ics ↔ iCloud Calendar (phone sync)
```

## Bitable Schema (Required Fields)

| Field Name | Type | Description |
|------------|------|-------------|
| `序号` | Text | Auto-increment |
| `任务名称` | Text | Task/event title |
| `分组` | SingleSelect | First-level grouping (日程表/工作/生活/其他) |
| `标签` | MultiSelect | Second-level tags |
| `优先级` | SingleSelect | 高/中/低 |
| `状态` | SingleSelect | 待执行/进行中/已完成/推迟 |
| `循环类型` | SingleSelect | 不循环/每周/每两周/每月/每年/不定期 |
| `日历分类` | SingleSelect | 不同步/个人/工作/家庭共享 |
| `完成次数` | Number | How many times completed (for recurring) |
| `计划日期` | Date | Planned date |
| `开始时间` | DateTime | Start time (UTC milliseconds) |
| `结束时间` | DateTime | End time (UTC milliseconds) |
| `iCloud事件ID` | Text | UID for .ics file |
| `父任务` | Link | Parent task (for sub-tasks) |
| `描述` | Text | Extra notes |

## Timezone Rules (Critical)

**Always follow these rules to avoid wrong time display**:

1. **Feishu Bitable**:
   - Store **UTC milliseconds timestamp**
   - Feishu automatically converts to user's local timezone for display
   - Format datetime fields as `yyyy/MM/dd HH:mm` to show both date and time

2. **iCloud .ics**:
   - Store **local time (China Standard Time = UTC+8)** with `TZID=Asia/Shanghai`
   - Do NOT convert to UTC for storage in .ics
   - iOS will display correctly with timezone info preserved

**Example**: User says "this Sunday 1pm to 5:30pm" (CST)
- Feishu: `2026-04-26 13:00 CST` → UTC → `1777179600000` ms → stored in Bitable
- iCloud: `DTSTART;TZID=Asia/Shanghai:20260426T130000` → stored in .ics

## Sync Strategy & Conflict Resolution

**Core rule**: Feishu Bitable is the single source of truth. iCloud calendar is only for phone client display.

| Conflict scenario | Resolution |
|-----------------|------------|
| Feishu modified, iCloud not modified | Feishu → overwrite iCloud |
| iCloud modified, Feishu not modified | Manual trigger pull → iCloud → overwrite Feishu |
| Both modified | **Feishu wins** → Feishu overwrite iCloud |
| Feishu deleted, iCloud still exists | Feishu delete → delete in iCloud |
| iCloud deleted, Feishu still exists | Pull sync → Feishu mark as deleted |

## Two-way Sync Process

### 1. iCloud → Feishu (Pull Changes)

Steps:
```bash
1. vdirsyncer sync <pair-name>    # Pull latest from iCloud to local .ics
2. Parse each .ics → extract UID, summary, start/end time with timezone
3. For each event:
   - If already exists in Bitable (match by UID) → update start/end time
   - If not exists → create new record
4. Auto-detect cycle type:
   - ≥ 2 occurrences with same name → "每周"
   - Contains "医院预约" → "不定期"
   - Otherwise → "不循环"
5. Log the sync operation to operation log
```

### 2. Feishu → iCloud (Push Changes)

Steps:
```bash
1. Query Bitable for all records where 日历分类 != "不同步"
2. For each record:
   - Generate/update .ics file with correct timezone format
   - Keep original UID for incremental sync
   - If record deleted in Feishu → delete local .ics file
3. vdirsyncer sync <pair-name>    # Push all changes to iCloud
4. Log the sync operation to operation log
```

### Delete Handling

- When Feishu record is deleted via assistant → delete corresponding .ics file by UID → sync → iCloud deletes it
- When Feishu record is deleted manually → next full sync will detect missing UID → delete from iCloud

## Daily Workflow

### Morning (8:00 CST)
1. Query Bitable for today's (and tomorrow's if needed) events
   - Filter: `计划日期 == today AND 状态 == 待执行`
2. Group by calendar category
3. Send formatted message to user with:
   - Today's calendar events (start time + title)
   - Today's todos (no time)

### Evening (8:00 CST)
1. Query today's pending tasks/events
2. Send confirmation list to user
   - Default: all marked as completed automatically
   - User only needs to reply uncompleted/postponed items
3. After user confirmation:
   - Mark confirmed items as "已完成"
   - For recurring tasks: increment completion count → calculate next occurrence date → create new record/sync to iCloud
   - For non-recurring: keep as completed
   - For postponed: reschedule to new date → update Bitable → sync to iCloud
4. Sync all changes to iCloud

## Natural Language Parsing

Supports adding tasks/events via natural language:

Examples:
- `本周日下午1点到5点半 周日活动 - 玩加晚饭` → parse date/time → create event in family calendar
- `下周五 医院预约 笑笑验血` → parse date → "不定期" cycle → add
- `每周日上午9点 妙妙踢球` → parse recurring weekly → add

Automatic inference:
- If no end time → default 1 hour duration
- If no date → defaults to today/tomorrow based on context
- If contains "每周"/"每月" → auto set cycle type

## Operation Logging & Statistics

All operations are logged to `~/.personal-assistant/operations.log` in JSONL format.

Each log entry includes:
- `timestamp`: UTC milliseconds
- `utc_time`: ISO 8601 UTC time
- `cst_time`: ISO 8601 China time
- `operation`: Type of operation (`create`/`update`/`delete`/`complete`/`reschedule`/`sync`)
- `task_name`: Task/event name
- `record_id`: Feishu record ID
- `details`: Extra details (e.g. old/new time for reschedule)

Statistics are stored in `~/.personal-assistant/stats.json`:
- `completed_by_day`: Completed count per day (CST)
- `completed_by_month`: Completed count per month (CST)
- `total_completed`: Total completed all time
- `created_total`: Total created all time

**Every write operation must update log and statistics**:
```python
from memory import OperationLog, Statistics

oplog = OperationLog()
oplog.log('create', task_name, record_id, details={'start_time': start_ts})

stats = Statistics()
stats.record_created()
```

## Configuration

### Required: vdirsyncer config (`~/.vdirsyncer/config`)

Example for multiple iCloud calendars:
```ini
[general]
status_path = "~/.local/share/vdirsyncer/status/"

# Family shared calendar (new)
[pair icloud_family_new]
a = "icloud_remote_family_new"
b = "icloud_family_new_local"
collections = ["family-new"]
conflict_resolution = "a wins"

[storage icloud_remote_family_new]
type = "caldav"
url = "https://caldav.icloud.com/"
username = "your-email@icloud.com"
password = "your-app-specific-password"

[storage icloud_family_new_local]
type = "filesystem"
path = "~/.local/share/vdirsyncer/calendars/icloud_family_new/"
fileext = ".ics"

# Add more pairs for personal/work calendars as needed
```

### Required: khal config (`~/.config/khal/config`)

```ini
[calendars]
[[family-new]]
path = ~/.local/share/vdirsyncer/calendars/icloud_family_new/family-new
displayname = 家庭共享（新）
type = calendar

# Add more calendars here
[default]
default_calendar = family-new
highlight_event_days = True

[locale]
timeformat = %H:%M
dateformat = %Y-%m-%d
longdateformat = %Y-%m-%d
```

### Required: Feishu Bitable

- Create Bitable app
- Create table with required fields (see schema above)
- Configure datetime fields `开始时间`/`结束时间` with `date_formatter: "yyyy/MM/dd HH:mm"` to show time

## Common Issues & Solutions

1. **iOS shows wrong time**:
   - ❌ Bad: Storing UTC time without TZID → iOS displays UTC as local time
   - ✅ Good: Store local time with `TZID=Asia/Shanghai` in .ics

2. **Feishu doesn't show time, only date**:
   - ❌ Bad: Default formatter only shows date
   - ✅ Good: Update field property `date_formatter: "yyyy/MM/dd HH:mm"`

3. **vdirsyncer error: Unknown option `autocreate`**:
   - Cause: Old vdirsyncer version doesn't support modern options
   - Fix: Manually specify collection after discovery instead of using `autocreate`

4. **UnicodeEncodeError when creating files**:
   - Cause: Non-ASCII characters in filename
   - Fix: Use UUID as filename, store title inside .ics only

5. **Timezone calculation errors**:
   - Always: User input → China time → convert to UTC milliseconds for Feishu
   - Always: Store in .ics as China time with `TZID=Asia/Shanghai`

## Usage Examples

### Add new event from natural language
```
User: "本周日下午1点到5点半 周日活动 - 玩加晚饭"
Assistant:
  1. Parse date/time → 2026-04-26 13:00 - 17:30 CST
  2. Convert to UTC milliseconds for Feishu
  3. Create record in Feishu Bitable, category "家庭共享"
  4. Generate .ics with TZID=Asia/Shanghai
  5. vdirsyncer sync → pushes to iCloud
  6. Confirm with user
```

### Evening confirmation
```
Assistant pushes:
---
**今日待办确认** (默认全部完成，请回复未完成/推迟):

1. 13:00 - 17:30 周日活动 - 玩加晚饭
2. 19:00 笑笑小提琴

User replies: "笑笑小提琴推迟到下周日"
Assistant:
  1. Mark "周日活动" as completed
  2. Reschedule "笑笑小提琴" to next Sunday → update Bitable
  3. Update .ics → sync to iCloud
  4. If recurring → generate next occurrence after completion
```

## Cron Job Setup (for daily reports)

Add to crontab:
```
# Morning report at 8:00 CST (UTC 0:00)
0 0 * * * /path/to/daily-morning-report.sh >> /var/log/personal-assistant.log 2>&1
# Evening confirmation at 8:00 CST (UTC 12:00)
0 12 * * * /path/to/evening-confirmation.sh >> /var/log/personal-assistant.log 2>&1
```
