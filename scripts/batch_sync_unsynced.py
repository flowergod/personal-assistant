#!/usr/bin/env python3
"""
Batch sync all unsynced events from Feishu Bitable to iCloud Calendar
- Only syncs records that have: start_time + end_time + calendar_category + empty iCloudEventID
- Follows the correct format: complete VTIMEZONE, 15min reminder, correct directory structure
- Updates Feishu record with iCloud UID after creation
- Syncs to iCloud via vdirsyncer
"""

import os
import sys
import subprocess
import uuid
import datetime
import pytz

# Configuration - matches the global config
APP_TOKEN = os.environ.get('FEISHU_APP_TOKEN', 'YmMcb4PUlaTIAmshS6EcFqPenff')
TABLE_ID = os.environ.get('FEISHU_TABLE_ID', 'tbllwg2t4sEJ64i1')

# Calendar mapping - matches vdirsyncer config
CALENDAR_MAPPING = {
    '个人': {
        'vdir_dir': '/home/node/.local/share/vdirsyncer/calendars/icloud_personal/F7D25790-4368-447C-96FF-4F7FE022AE1C/F7D25790-4368-447C-96FF-4F7FE022AE1C',
        'sync_pair': 'icloud_personal'
    },
    '工作': {
        'vdir_dir': '/home/node/.local/share/vdirsyncer/calendars/icloud_work/D03AAE8F-D142-42CF-8FF2-BA7AB2E83092/D03AAE8F-D142-42CF-8FF2-BA7AB2E83092',
        'sync_pair': 'icloud_work'
    },
    '家庭共享': {
        'vdir_dir': '/home/node/.local/share/vdirsyncer/calendars/icloud_family_new/family-new/family-new',
        'sync_pair': 'icloud_family_new'
    }
}

def get_complete_timezone_def():
    """Return complete VTIMEZONE block for Asia/Shanghai, same as iOS generates"""
    return """BEGIN:VTIMEZONE
TZID:Asia/Shanghai
X-LIC-LOCATION:Asia/Shanghai
BEGIN:STANDARD
DTSTART:19010101T000000
RDATE:19010101T000000
TZNAME:CST
TZOFFSETFROM:+080543
TZOFFSETTO:+0800
END:STANDARD
BEGIN:DAYLIGHT
DTSTART:19400601T000000
RDATE:19400601T000000
RDATE:19410315T000000
RDATE:19420131T000000
RDATE:19460515T000000
RDATE:19470415T000000
RDATE:19860504T020000
TZNAME:CDT
TZOFFSETFROM:+0800
TZOFFSETTO:+0900
END:DAYLIGHT
BEGIN:STANDARD
DTSTART:19401012T235959
RDATE:19401012T235959
RDATE:19411101T235959
RDATE:19450901T235959
RDATE:19460930T235959
RDATE:19471031T235959
RDATE:19480930T235959
RDATE:19490528T000000
TZNAME:CST
TZOFFSETFROM:+0900
TZOFFSETTO:+0800
END:STANDARD
BEGIN:DAYLIGHT
DTSTART:19480501T000000
RRULE:FREQ=YEARLY;UNTIL=19490430T160000Z;BYMONTH=5
TZNAME:CDT
TZOFFSETFROM:+0800
TZOFFSETTO:+0900
END:DAYLIGHT
BEGIN:STANDARD
DTSTART:19860914T020000
RRULE:FREQ=YEARLY;UNTIL=19910914T170000Z;BYMONTH=9;BYMONTHDAY=11 12 13 14 15 16 17;BYDAY=SU
TZNAME:CST
TZOFFSETFROM:+0900
TZOFFSETTO:+0800
END:STANDARD
BEGIN:DAYLIGHT
DTSTART:19870412T020000
RRULE:FREQ=YEARLY;UNTIL=19910413T180000Z;BYMONTH=4;BYMONTHDAY=11 12 13 14 15 16 17;BYDAY=SU
TZNAME:CDT
TZOFFSETFROM:+0800
TZOFFSETTO:+0900
END:DAYLIGHT
END:VTIMEZONE
"""

def create_ics_file(uid: str, title: str, start_dt_cst: datetime.datetime, end_dt_cst: datetime.datetime, location: str, filepath: str):
    """Create .ics file with correct format matching iOS output"""
    def format_cst(dt):
        return dt.strftime('%Y%m%dT%H%M%S')

    now_utc = datetime.datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')
    tz_block = get_complete_timezone_def()

    ics_content = f"""BEGIN:VCALENDAR
CALSCALE:GREGORIAN
VERSION:2.0
PRODID:-//PersonalAssistant//OpenClaw//EN
BEGIN:VEVENT
CREATED:{now_utc}
DTEND;TZID=Asia/Shanghai:{format_cst(end_dt_cst)}
DTSTAMP:{now_utc}
DTSTART;TZID=Asia/Shanghai:{format_cst(start_dt_cst)}
LAST-MODIFIED:{now_utc}
SEQUENCE:0
SUMMARY:{title}
"""
    if location:
        ics_content += f"LOCATION:{location}\n"

    ics_content += f"""UID:{uid}
TRANSP:OPAQUE
BEGIN:VALARM
ACTION:DISPLAY
DESCRIPTION:提醒事项
TRIGGER:-PT15M
UID:{uuid.uuid4().hex}
X-APPLE-DEFAULT-ALARM:TRUE
X-WR-ALARMUID:{uuid.uuid4().hex}
END:VALARM
END:VEVENT
{tz_block}
END:VCALENDAR
"""

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(ics_content)

    return filepath

def update_feishu_uid(record_id: str, uid: str):
    """Update Feishu Bitable record with iCloud UID using openclaw CLI"""
    import json
    cmd = f"""openclaw tool call feishu_bitable_app_table_record '{{"action": "update", "app_token": "{APP_TOKEN}", "table_id": "{TABLE_ID}", "record_id": "{record_id}", "fields": {{"iCloud事件ID": "{uid}"}}}}'"""
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return result.returncode == 0

def ms_to_cst(start_ms: int, end_ms: int):
    """Convert UTC millisecond timestamps to CST datetime objects"""
    tz = pytz.timezone('Asia/Shanghai')
    start_dt_cst = datetime.datetime.utcfromtimestamp(start_ms / 1000).replace(tzinfo=pytz.utc).astimezone(tz)
    end_dt_cst = datetime.datetime.utcfromtimestamp(end_ms / 1000).replace(tzinfo=pytz.utc).astimezone(tz)
    return start_dt_cst, end_dt_cst

def main():
    # We need to fetch all records from Feishu first
    # This script expects that you've already fetched the list and filtered it
    # For fully automatic operation, call the openclaw tool to get all records then filter

    # Hardcoded list of records to sync - in automatic mode this would be generated dynamically
    # For this run we have the list ready from earlier manual processing

    records_to_sync = [
        # (record_id, title, start_ms, end_ms, category, location)
        ("recvhoRNxagcH8", "检查所有 进行中 项目，确保每个项目的\"下一步行动\"明确", 1777046400000, 1777132740000, "工作", ""),
        ("recvhoRNxa5C1Y", "徐斌交流", 1776810000000, 1776813600000, "工作", ""),
        ("recvhoRNxaE3N4", "周小结", 1777046400000, 1777132740000, "工作", ""),
        ("recvhoRNxal5A3", "联系小伙伴，安排饭局", 1777305600000, 1777391940000, "工作", ""),
        ("recvhoRNxabFU7", "执行归档", 1777046400000, 1777132740000, "工作", ""),
        ("recvhoRQjMRlVn", "领移动会员", 1777996800000, 1778083140000, "个人", ""),
        ("recvhoRQjMYVPX", "付手机费", 1777996800000, 1778083140000, "个人", ""),
        ("recvhoRQjMxN0E", "盘账", 1777478400000, 1777564740000, "个人", ""),
        ("recvhoRQjMDbvY", "发工资", 1776614400000, 1776700740000, "个人", ""),
        ("recvhoRQjMeRSs", "还信用卡-招商银行", 1776960000000, 1777046340000, "个人", ""),
        ("recvhpZ6nv80h4", "约xrc午饭", 1782604800000, 1782608400000, "工作", ""),
        ("recvhussxEgPYi", "晨星峰会", 1776992400000, 1777021200000, "工作", "上海浦东丽思卡尔顿酒店"),
    ]

    success_count = 0
    fail_count = 0
    synced_pairs = []

    for rec in records_to_sync:
        record_id, title, start_ms, end_ms, category, location = rec

        if category not in CALENDAR_MAPPING:
            print(f"⚠️  Unknown category '{category}', skipping '{title}'")
            fail_count += 1
            continue

        cal_config = CALENDAR_MAPPING[category]

        # Convert timestamps
        try:
            start_dt_cst, end_dt_cst = ms_to_cst(start_ms, end_ms)
        except Exception as e:
            print(f"❌ Failed to convert timestamps for '{title}': {e}")
            fail_count += 1
            continue

        # Generate UID
        uid = f"{uuid.uuid4().hex}@{int(datetime.datetime.now().timestamp())}@personal-assistant"
        print(f"\n=== Processing: {title} ===")
        print(f"   UID: {uid}")
        print(f"   Time: {start_dt_cst.strftime('%Y-%m-%d %H:%M')} - {end_dt_cst.strftime('%Y-%m-%d %H:%M')} [{category}]")

        # Create .ics file in correct directory
        filepath = os.path.join(cal_config['vdir_dir'], f"{uid}.ics")
        try:
            create_ics_file(uid, title, start_dt_cst, end_dt_cst, location, filepath)
            print(f"   Created: {filepath}")
        except Exception as e:
            print(f"   ❌ Failed to create .ics: {e}")
            fail_count += 1
            continue

        # Update Feishu
        success = update_feishu_uid(record_id, uid)
        if not success:
            print(f"   ⚠️ Failed to update Feishu")
        else:
            print(f"   ✅ Updated Feishu record with iCloud UID")

        success_count += 1
        synced_pairs.append((cal_config['sync_pair'], uid))

    # Sync all affected calendars
    print(f"\n=== Syncing all affected calendars ===")
    seen_pairs = set()
    for sync_pair, _ in synced_pairs:
        if sync_pair not in seen_pairs:
            print(f"Syncing {sync_pair}...")
            result = subprocess.run(['vdirsyncer', 'sync', sync_pair], capture_output=True, text=True)
            if result.returncode != 0:
                print(f"⚠️ Sync {sync_pair} failed:\n{result.stderr}")
            seen_pairs.add(sync_pair)

    print(f"\n=== Batch sync complete ===")
    print(f"✅ Success: {success_count}, ❌ Failed: {fail_count}")

if __name__ == '__main__':
    exit(main())
