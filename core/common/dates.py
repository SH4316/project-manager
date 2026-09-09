from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

from django.utils import timezone

KST = ZoneInfo("Asia/Seoul")


def now_kst():
    return timezone.now().astimezone(KST)


def today_kst() -> date:
    return now_kst().date()


def week_bounds(d: date | None = None) -> tuple[date, date]:
    """(이번 주 월요일, 이번 주 일요일)"""
    d = d or today_kst()
    monday = d - timedelta(days=d.weekday())
    return monday, monday + timedelta(days=6)


def last_week_start(d: date | None = None) -> date:
    """직전 주 월요일"""
    monday, _ = week_bounds(d)
    return monday - timedelta(days=7)


def kst_day_range(day: date):
    """day 00:00 KST 부터 다음날 00:00 KST 까지의 aware datetime 쌍"""
    start = datetime.combine(day, datetime.min.time(), tzinfo=KST)
    return start, start + timedelta(days=1)


def kst_week_range(week_start: date):
    """week_start 00:00 KST 부터 7일 뒤 00:00 KST 까지"""
    start = datetime.combine(week_start, datetime.min.time(), tzinfo=KST)
    return start, start + timedelta(days=7)


def fmt_md(d: date | None) -> str:
    """'9월 9일'. None이면 빈 문자열."""
    return f"{d.month}월 {d.day}일" if d else ""
