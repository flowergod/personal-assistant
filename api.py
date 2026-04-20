#!/usr/bin/env python3
"""
Personal Assistant API
- Receive natural language text
- Parse into task/event
- Create record in Feishu Bitable
- Sync to iCloud via vdirsyncer
- Return result
"""

import os
import re
import uuid
import json
from datetime import datetime, timedelta
from typing import Optional, List
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

import sys
sys.path.append('/app/.openclaw/extensions/openclaw-lark/skills/feishu-bitable')

# Configuration - load from environment or config
APP_TOKEN = os.environ.get('FEISHU_APP_TOKEN', 'YmMcb4PUlaTIAmshS6EcFqPenff')
TABLE_ID = os.environ.get('FEISHU_TABLE_ID', 'tbllwg2t4sEJ64i1')
VCAL_DIR = os.environ.get('VCAL_DIR', '/home/node/.local/share/vdirsyncer/calendars/icloud_family_new/family-new')
SYNC_PAIR = os.environ.get('VDIRSYNC_PAIR', 'icloud_family_new')

app = FastAPI(title="Personal Assistant API", version="1.0")

class ParseRequest(BaseModel):
    text: str
    category: Optional[str] = "家庭共享"  # 不同步/个人/工作/家庭共享
    group: Optional[str] = "日程表"
    priority: Optional[str] = "中"

class ParseResponse(BaseModel):
    success: bool
    title: str
    start_date: str
    start_time: Optional[str] = None
    end_date: Optional[str] = None
    end_time: Optional[str] = None
    cycle_type: str
    category: str
    feishu_record_id: Optional[str] = None
    icloud_uid: Optional[str] = None
    message: str

def parse_natural_language(text: str):
    """
    Parse natural language to extract date, time, title, cycle type
    """
    result = {
        'title': None,
        'start_dt': None,
        'end_dt': None,
        'cycle_type': '不循环',
    }

    # Detect cycle type
    if '每周' in text:
        result['cycle_type'] = '每周'
    elif '每月' in text:
        result['cycle_type'] = '每月'
    elif '每年' in text:
        result['cycle_type'] = '每年'
    elif '不定期' in text or '医院预约' in text:
        result['cycle_type'] = '不定期'

    # Relative dates
    today = datetime.now()
    # Get current week sunday
    days_until_sunday = 6 - today.weekday()
    this_sunday = today + timedelta(days=days_until_sunday)
    next_sunday = this_sunday + timedelta(days=7)

    # Patterns
    patterns = [
        # this week sunday
        (r'本周日|这个周日|周日', lambda: this_sunday),
        (r'下周日|下个周日', lambda: next_sunday),
        (r'明天|明日', lambda: today + timedelta(days=1)),
        (r'今天|今日', lambda: today),
    ]

    start_date = None
    for pattern, getter in patterns:
        if re.search(pattern, text):
            start_date = getter()
            break

    if not start_date:
        # Try explicit date format YYYY-MM-DD
        match = re.search(r'(\d{4})-(\d{1,2})-(\d{1,2})', text)
        if match:
            year = int(match.group(1))
            month = int(match.group(2))
            day = int(match.group(3))
            start_date = datetime(year, month, day)

    if not start_date:
        # Try Chinese date format "X月X日"
        match = re.search(r'(\d+)月(\d+)日', text)
        if match:
            month = int(match.group(1))
            day = int(match.group(2))
            year = today.year
            start_date = datetime(year, month, day)

    result['start_dt'] = start_date

    # Parse time range
    # 下午1点到5点半 → 13:00 - 17:30
    time_map = {
        '凌晨': (0, 6),
        '上午': (6, 12),
        '下午': (12, 18),
        '晚上': (18, 24),
    }

    start_hour = None
    start_minute = 0
    end_hour = None
    end_minute = 0

    # 1点 → 13 if afternoon/evening, 1 if morning
    match = re.search(r'(\d+)(点|时)(半)?', text)
    if match:
        h = int(match.group(1))
        is_half = match.group(3) == '半'
        # Check period
        for period, (start, end) in time_map.items():
            if period in text:
                if h < 12:
                    h = start + h
                break
        start_hour = h
        start_minute = 30 if is_half else 0

    # end time
    match = re.search(r'(到|至)(\d+)(点|时)(半)?', text)
    if match:
        h = int(match.group(2))
        is_half = match.group(4) == '半'
        for period, (start, end) in time_map.items():
            if period in text.split('到')[-1]:
                if h < 12:
                    h = start + h
                break
        end_hour = h
        end_minute = 30 if is_half else 0

    # If we have start date but no time → all day event
    if start_date and start_hour is None:
        # All day, start at 0:00 CST
        result['start_dt'] = datetime(start_date.year, start_date.month, start_date.day, 0, 0, 0)
        result['end_dt'] = datetime(start_date.year, start_date.month, start_date.day, 23, 59, 59)
    elif start_date and start_hour is not None:
        result['start_dt'] = datetime(start_date.year, start_date.month, start_date.day, start_hour, start_minute, 0)
        if end_hour is None:
            # default 1 hour
            end_hour = start_hour + 1
            end_minute = start_minute
        result['end_dt'] = datetime(start_date.year, start_date.month, start_date.day, end_hour, end_minute, 0)

    # Extract title - everything that's not date/time keywords
    title = text
    # Remove common date/time words
    remove_words = ['本周日', '这个周日', '周日', '下周日', '下个周日', '明天', '今日', '今天', '上午', '下午', '晚上', '凌晨', '点', '时', '半', '到', '至', '每周', '每月', '每年', '不定期', '医院预约']
    for word in remove_words:
        title = title.replace(word, '')
    title = title.strip()
    if not title:
        title = "未命名任务"
    result['title'] = title

    return result

def create_feishu_record(title: str, start_dt_cst: datetime, end_dt_cst: datetime, category: str, group: str, priority: str, cycle_type: str):
    """
    Create record in Feishu Bitable
    Feishu needs UTC milliseconds
    """
    # CST is UTC+8 → convert to UTC timestamp
    start_utc_ts = int(start_dt_cst.timestamp() - 8 * 3600) * 1000
    end_utc_ts = int(end_dt_cst.timestamp() - 8 * 3600) * 1000
    plan_date_ts = int((datetime(start_dt_cst.year, start_dt_cst.month, start_dt_cst.day, 0, 0, 0).timestamp() - 8 * 3600)) * 1000

    uid = f"{str(uuid.uuid4()).upper()}-{int(datetime.now().timestamp())}@icloud-sync"

    fields = {
        "任务名称": title,
        "分组": group,
        "优先级": priority,
        "状态": "待执行",
        "计划日期": plan_date_ts,
        "开始时间": start_utc_ts,
        "结束时间": end_utc_ts,
        "日历分类": category,
        "循环类型": cycle_type,
        "完成次数": 0,
        "iCloud事件ID": uid,
    }

    # Call Feishu API via openclaw tool (this runs in OpenClaw environment)
    from openclaw.tools import call_tool
    result = call_tool('feishu_bitable_app_table_record', {
        'action': 'create',
        'app_token': APP_TOKEN,
        'table_id': TABLE_ID,
        'fields': fields,
    })

    if result.get('error'):
        return None, result.get('message')

    record_id = result.get('record', {}).get('record_id')
    return {'record_id': record_id, 'uid': uid}, None

def create_ics(uid: str, title: str, start_dt_cst: datetime, end_dt_cst: datetime):
    """
    Create .ics file with correct timezone (TZID=Asia/Shanghai for CST times)
    """
    # Format: DTSTART;TZID=Asia/Shanghai:YYYYMMDDTHHMMSS
    def format_cst(dt):
        return dt.strftime('%Y%m%dT%H%M%S')

    ics_content = f"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//PersonalAssistant//OpenClaw//EN
BEGIN:VEVENT
SUMMARY:{title}
DTSTART;TZID=Asia/Shanghai:{format_cst(start_dt_cst)}
DTEND;TZID=Asia/Shanghai:{format_cst(end_dt_cst)}
DTSTAMP:{datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}
UID:{uid}
END:VEVENT
END:VCALENDAR
"""

    filepath = os.path.join(VCAL_DIR, f"{uid}.ics")
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(ics_content)

    return filepath

def sync_to_icloud():
    """Run vdirsyncer sync"""
    import subprocess
    result = subprocess.run(['vdirsyncer', 'sync', SYNC_PAIR], capture_output=True, text=True)
    return {
        'success': result.returncode == 0,
        'stdout': result.stdout,
        'stderr': result.stderr,
    }

@app.post("/parse", response_model=ParseResponse)
def parse_task(request: ParseRequest):
    """
    Parse natural language task, create in Feishu, sync to iCloud
    """
    parsed = parse_natural_language(request.text)

    if not parsed['start_dt']:
        raise HTTPException(status_code=400, detail="Could not parse date from text")

    title = parsed['title']
    start_dt = parsed['start_dt']
    end_dt = parsed['end_dt']
    cycle_type = parsed['cycle_type']

    if not end_dt:
        # Default 1 hour
        end_dt = start_dt + timedelta(hours=1)

    # Create in Feishu
    result, error = create_feishu_record(
        title=title,
        start_dt_cst=start_dt,
        end_dt_cst=end_dt,
        category=request.category,
        group=request.group,
        priority=request.priority,
        cycle_type=cycle_type,
    )

    if error:
        return ParseResponse(
            success=False,
            title=title,
            start_date=start_dt.strftime('%Y-%m-%d'),
            start_time=start_dt.strftime('%H:%M'),
            cycle_type=cycle_type,
            category=request.category,
            message=f"Feishu error: {error}"
        )

    record_id = result['record_id']
    uid = result['uid']

    # Create .ics
    create_ics(uid, title, start_dt, end_dt)

    # Sync to iCloud
    sync_result = sync_to_icloud()

    if not sync_result['success']:
        return ParseResponse(
            success=False,
            title=title,
            start_date=start_dt.strftime('%Y-%m-%d'),
            start_time=start_dt.strftime('%H:%M'),
            end_date=end_dt.strftime('%Y-%m-%d'),
            end_time=end_dt.strftime('%H:%M'),
            cycle_type=cycle_type,
            category=request.category,
            feishu_record_id=record_id,
            icloud_uid=uid,
            message=f"iCloud sync failed: {sync_result['stderr']}"
        )

    return ParseResponse(
        success=True,
        title=title,
        start_date=start_dt.strftime('%Y-%m-%d'),
        start_time=start_dt.strftime('%H:%M'),
        end_date=end_dt.strftime('%Y-%m-%d'),
        end_time=end_dt.strftime('%H:%M'),
        cycle_type=cycle_type,
        category=request.category,
        feishu_record_id=record_id,
        icloud_uid=uid,
        message="Task created successfully and synced to iCloud"
    )

@app.get("/health")
def health():
    return {"status": "ok"}

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get('PORT', 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
