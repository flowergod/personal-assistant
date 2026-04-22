#!/usr/bin/env python3
"""
Sync a single Feishu Bitable record to iCloud Calendar
- Generates .ics file with correct timezone (CST = Asia/Shanghai)
- Updates Feishu record with iCloud UID
- Runs vdirsyncer sync to push to iCloud

Usage:
python sync_single_to_icloud.py --record-id REC_ID --title "Task Name" --start-cst "2026-04-24 09:00" --end-cst "2026-04-24 17:00" --category work
"""

import os
import argparse
import uuid
import datetime
import pytz
import subprocess

# Configuration - matches api.py
APP_TOKEN = os.environ.get('FEISHU_APP_TOKEN', 'YmMcb4PUlaTIAmshS6EcFqPenff')
TABLE_ID = os.environ.get('FEISHU_TABLE_ID', 'tbllwg2t4sEJ64i1')

# Calendar mapping
CALENDAR_MAPPING = {
    '个人': {
        'vdir_dir': '/home/node/.local/share/vdirsyncer/calendars/icloud_personal/F7D25790-4368-447C-96FF-4F7FE022AE1C',
        'sync_pair': 'icloud_personal'
    },
    '工作': {
        'vdir_dir': '/home/node/.local/share/vdirsyncer/calendars/icloud_work/D03AAE8F-D142-42CF-8FF2-BA7AB2E83092',
        'sync_pair': 'icloud_work'
    },
    '家庭共享': {
        'vdir_dir': '/home/node/.local/share/vdirsyncer/calendars/icloud_family_new/family-new',
        'sync_pair': 'icloud_family_new'
    }
}

def parse_datetime_cst(dt_str):
    """Parse datetime string 'YYYY-MM-DD HH:MM' in CST timezone"""
    tz = pytz.timezone('Asia/Shanghai')
    dt = datetime.datetime.strptime(dt_str, '%Y-%m-%d %H:%M')
    return tz.localize(dt)

def create_ics(uid: str, title: str, start_dt_cst: datetime.datetime, end_dt_cst: datetime.datetime, filepath: str):
    """Create .ics file with correct timezone"""
    def format_cst(dt):
        return dt.strftime('%Y%m%dT%H%M%S')

    ics_content = f"""BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//PersonalAssistant//OpenClaw//EN
BEGIN:VEVENT
SUMMARY:{title}
DTSTART;TZID=Asia/Shanghai:{format_cst(start_dt_cst)}
DTEND;TZID=Asia/Shanghai:{format_cst(end_dt_cst)}
DTSTAMP:{datetime.datetime.utcnow().strftime('%Y%m%dT%H%M%SZ')}
UID:{uid}
END:VEVENT
END:VCALENDAR
"""

    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(ics_content)

    return filepath

def update_feishu_uid(record_id: str, uid: str):
    """Update Feishu Bitable record with iCloud UID using openclaw CLI"""
    # We use openclaw exec to call the tool since we can't import it here
    import json
    cmd = f"""openclaw tool call feishu_bitable_app_table_record '{json.dumps({
        "action": "update",
        "app_token": APP_TOKEN,
        "table_id": TABLE_ID,
        "record_id": record_id,
        "fields": {{"iCloud事件ID": uid}}
    })}'"""
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    return result.returncode == 0

def main():
    parser = argparse.ArgumentParser(description='Sync single Feishu record to iCloud')
    parser.add_argument('--record-id', required=True, help='Feishu record ID')
    parser.add_argument('--title', required=True, help='Event title')
    parser.add_argument('--start-cst', required=True, help='Start time in CST: "YYYY-MM-DD HH:MM"')
    parser.add_argument('--end-cst', required=True, help='End time in CST: "YYYY-MM-DD HH:MM"')
    parser.add_argument('--category', default='家庭共享', help='Calendar category: 个人/工作/家庭共享')
    args = parser.parse_args()

    # Get calendar config
    if args.category not in CALENDAR_MAPPING:
        print(f"Error: category must be one of {list(CALENDAR_MAPPING.keys())}")
        return 1
    cal_config = CALENDAR_MAPPING[args.category]

    # Parse datetimes
    try:
        start_dt_cst = parse_datetime_cst(args.start_cst)
        end_dt_cst = parse_datetime_cst(args.end_cst)
    except ValueError as e:
        print(f"Error parsing datetime: {e}")
        print("Format should be: 'YYYY-MM-DD HH:MM' (e.g. '2026-04-24 09:00')")
        return 1

    # Generate UID
    uid = f"{uuid.uuid4().hex}@{int(datetime.datetime.now().timestamp())}@personal-assistant"
    print(f"Generated UID: {uid}")

    # Create .ics
    filepath = os.path.join(cal_config['vdir_dir'], f"{uid}.ics")
    create_ics(uid, args.title, start_dt_cst, end_dt_cst, filepath)
    print(f"Created .ics: {filepath}")

    # Update Feishu
    success = update_feishu_uid(args.record_id, uid)
    if not success:
        print("Warning: Failed to update Feishu with UID")
    else:
        print("Updated Feishu record with iCloud UID")

    # Sync to iCloud
    print(f"\nSyncing to iCloud... ({cal_config['sync_pair']})")
    result = subprocess.run(['vdirsyncer', 'sync', cal_config['sync_pair']], capture_output=True, text=True)
    if result.returncode != 0:
        print(f"Sync failed:\n{result.stderr}")
        return 1

    print("\n✅ Sync completed successfully!")
    print(f"   Event: {args.title}")
    print(f"   Time: {args.start_cst} - {args.end_cst} (CST)")
    print(f"   Calendar: {args.category}")
    print(f"   Feishu Record ID: {args.record_id}")
    print(f"   iCloud UID: {uid}")

    return 0

if __name__ == '__main__':
    exit(main())
