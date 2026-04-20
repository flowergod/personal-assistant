#!/usr/bin/env python3
"""
Memory module for personal-assistant
- Log all operations (add/edit/delete/complete/reschedule)
- Provide statistics and history query
- Automatic next occurrence calculation for recurring tasks
- Conflict detection (time overlapping)
"""

import os
import json
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Any

LOG_FILE = os.path.expanduser("~/.personal-assistant/operations.log")
STATS_FILE = os.path.expanduser("~/.personal-assistant/stats.json")

class OperationLog:
    """Operation logging"""

    OP_TYPES = [
        'create',      # Create new task/event
        'update',      # Update task/event
        'delete',      # Delete task/event
        'complete',    # Mark task as completed
        'reschedule',  # Reschedule task
        'sync',        # Sync with iCloud
    ]

    def __init__(self, log_file: str = LOG_FILE):
        self.log_file = log_file
        os.makedirs(os.path.dirname(log_file), exist_ok=True)
        if not os.path.exists(log_file):
            with open(log_file, 'w', encoding='utf-8') as f:
                f.write("# Operation log for personal-assistant\n")
                f.write("# format: jsonl\n")

    def log(self, operation: str, task_name: str, record_id: str, details: Optional[Dict] = None) -> None:
        """Log an operation"""
        if operation not in self.OP_TYPES:
            print(f"Warning: unknown operation type {operation}")

        entry = {
            'timestamp': int(datetime.utcnow().timestamp() * 1000),
            'utc_time': datetime.utcnow().isoformat(),
            'cst_time': (datetime.utcnow() + timedelta(hours=8)).isoformat(),
            'operation': operation,
            'task_name': task_name,
            'record_id': record_id,
            'details': details or {},
        }

        with open(self.log_file, 'a', encoding='utf-8') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')

    def query(self, start_ts: Optional[int] = None, end_ts: Optional[int] = None,
              operation: Optional[str] = None, task_name: Optional[str] = None) -> List[Dict]:
        """Query operation history"""
        results = []
        if not os.path.exists(self.log_file):
            return results

        with open(self.log_file, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                try:
                    entry = json.loads(line)
                    match = True
                    if start_ts and entry['timestamp'] < start_ts:
                        match = False
                    if end_ts and entry['timestamp'] > end_ts:
                        match = False
                    if operation and entry['operation'] != operation:
                        match = False
                    if task_name and task_name not in entry['task_name']:
                        match = False
                    if match:
                        results.append(entry)
                except:
                    continue

        return results

    def tail(self, n: int = 10) -> List[Dict]:
        """Get last n operations"""
        if not os.path.exists(self.log_file):
            return []

        with open(self.log_file, 'r', encoding='utf-8') as f:
            lines = f.readlines()

        lines = [line.strip() for line in lines if line.strip() and not line.startswith('#')]
        result = []
        for line in lines[-n:]:
            try:
                result.append(json.loads(line))
            except:
                continue
        return result

class Statistics:
    """Statistics for completed tasks"""

    def __init__(self, stats_file: str = STATS_FILE):
        self.stats_file = stats_file
        os.makedirs(os.path.dirname(stats_file), exist_ok=True)
        self._load()

    def _load(self):
        if os.path.exists(self.stats_file):
            with open(self.stats_file, 'r', encoding='utf-8') as f:
                self.data = json.load(f)
        else:
            self.data = {
                'completed_by_day': {},
                'completed_by_month': {},
                'total_completed': 0,
                'created_total': 0,
            }
            self._save()

    def _save(self):
        with open(self.stats_file, 'w', encoding='utf-8') as f:
            json.dump(self.data, f, indent=2, ensure_ascii=False)

    def record_completed(self, task_name: str, record_id: str) -> None:
        """Record a completed task"""
        today_cst = (datetime.utcnow() + timedelta(hours=8)).strftime('%Y-%m-%d')
        month_cst = (datetime.utcnow() + timedelta(hours=8)).strftime('%Y-%m')

        # Daily
        if today_cst not in self.data['completed_by_day']:
            self.data['completed_by_day'][today_cst] = 0
        self.data['completed_by_day'][today_cst] += 1

        # Monthly
        if month_cst not in self.data['completed_by_month']:
            self.data['completed_by_month'][month_cst] = 0
        self.data['completed_by_month'][month_cst] += 1

        self.data['total_completed'] += 1
        self._save()

    def record_created(self) -> None:
        """Record a created task"""
        self.data['created_total'] += 1
        self._save()

    def get_stats(self, month: Optional[str] = None) -> Dict:
        """Get statistics"""
        if month:
            completed = self.data['completed_by_month'].get(month, 0)
            return {
                'month': month,
                'completed': completed,
                'total_completed': self.data['total_completed'],
                'created_total': self.data['created_total'],
            }
        else:
            return {
                'total_completed': self.data['total_completed'],
                'created_total': self.data['created_total'],
                'last_7_days': sum(
                    cnt for day, cnt in self.data['completed_by_day'].items()
                    if day >= (datetime.utcnow() + timedelta(hours=8) - timedelta(days=7)).strftime('%Y-%m-%d')
                ),
                'last_30_days': sum(
                   cnt for day, cnt in self.data['completed_by_day'].items()
                    if day >= (datetime.utcnow() + timedelta(hours=8) - timedelta(days=30)).strftime('%Y-%m-%d')
                ),
            }

    def monthly_report(self) -> str:
        """Generate monthly report text"""
        stats = self.get_stats()
        current_month = (datetime.utcnow() + timedelta(hours=8)).strftime('%Y-%m')
        current_stats = self.get_stats(current_month)

        report = f"📊 **{current_month} 任务统计**\n\n"
        report += f"- 本月完成: {current_stats.get('completed', 0)}\n"
        report += f"- 累计完成: {stats['total_completed']}\n"
        report += f"- 累计创建: {stats['created_total']}\n"
        report += f"- 近 30 天完成: {stats['last_30_days']}\n"
        return report

class RecurringCalculator:
    """Calculate next occurrence for recurring tasks"""

    @staticmethod
    def next_occurrence(current_start_cst: datetime, cycle_type: str) -> datetime:
        """
        Calculate next occurrence based on cycle type
        Returns next start datetime in CST
        """
        if cycle_type == '每周':
            return current_start_cst + timedelta(weeks=1)
        elif cycle_type == '每两周':
            return current_start_cst + timedelta(weeks=2)
        elif cycle_type == '每月':
            # Same day next month
            year = current_start_cst.year
            month = current_start_cst.month
            day = current_start_cst.day
            if month == 12:
                return datetime(year + 1, 1, day, current_start_cst.hour, current_start_cst.minute)
            else:
                # Handle month length difference - clamp to last day
                try:
                    return datetime(year, month + 1, day, current_start_cst.hour, current_start_cst.minute)
                except ValueError:
                    # If day doesn't exist in next month, go to next month 1st
                    if month == 12:
                        return datetime(year + 1, 1, 1, current_start_cst.hour, current_start_cst.minute)
                    else:
                        return datetime(year, month + 1, 1, current_start_cst.hour, current_start_cst.minute)
        elif cycle_type == '每年':
            return datetime(current_start_cst.year + 1, current_start_cst.month, current_start_cst.day,
                          current_start_cst.hour, current_start_cst.minute)
        else:
            # Not recurring - return same date (shouldn't happen)
            return current_start_cst

class ConflictDetector:
    """Detect time conflicts (overlapping events)"""

    @staticmethod
    def has_conflict(existing_events: List[Dict], new_start_cst: datetime, new_end_cst: datetime) -> Optional[Dict]:
        """
        Check if new event conflicts with any existing event
        Returns conflicting event if found, None otherwise
        """
        for event in existing_events:
            # Get existing times
            # existing are UTC milliseconds from Feishu
            ex_start = datetime.fromtimestamp(event['start_time'] / 1000)
            ex_end = datetime.fromtimestamp(event['end_time'] / 1000)
            # Convert to CST for comparison
            ex_start_cst = ex_start + timedelta(hours=8)
            ex_end_cst = ex_end + timedelta(hours=8)

            # Check overlap
            # Overlap if: new_start < ex_end AND new_end > ex_start
            if new_start_cst < ex_end_cst and new_end_cst > ex_start_cst:
                return {
                    'conflict_with': event.get('task_name', 'unknown'),
                    'existing_start': ex_start_cst.strftime('%Y-%m-%d %H:%M'),
                    'existing_end': ex_end_cst.strftime('%Y-%m-%d %H:%M'),
                }

        return None

# Export
__all__ = [
    'OperationLog',
    'Statistics',
    'RecurringCalculator',
    'ConflictDetector',
]
