"""views.py — shared text rendering for the 'today' view (CLI + menu bar)."""
from __future__ import annotations

from datetime import date, datetime, timezone

try:
    from zoneinfo import ZoneInfo
    _BERLIN = ZoneInfo("Europe/Berlin")
except Exception:  # pragma: no cover
    _BERLIN = None

_WEEKDAYS = ["Mo", "Di", "Mi", "Do", "Fr", "Sa", "So"]


def _to_local(iso_utc: str) -> datetime:
    dt = datetime.fromisoformat(iso_utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(_BERLIN) if _BERLIN else dt


def _relative_days(target: datetime, now: datetime) -> str:
    delta = (target.date() - now.date()).days
    if delta < 0:
        return "ÜBERFÄLLIG"
    if delta == 0:
        return "heute"
    if delta == 1:
        return "morgen"
    return f"in {delta} Tagen"


def format_today(deadlines: list[dict], new_items: list, *, plain: bool = True,
                 max_new: int = 12, max_deadlines: int = 10) -> str:
    """Render the 'today' overview. `new_items` are sqlite3.Row or dicts."""
    now = datetime.now(_BERLIN) if _BERLIN else datetime.now()
    today = now.date()
    head = f"📅 Heute — {_WEEKDAYS[today.weekday()]}, {today.strftime('%d.%m.%Y')}"
    lines = [head, ""]

    # --- deadlines ---------------------------------------------------------
    lines.append(f"⏰ Anstehende Fristen (nächste 14 Tage):")
    if deadlines:
        for d in deadlines[:max_deadlines]:
            local = _to_local(d["due"])
            rel = _relative_days(local, now)
            wd = _WEEKDAYS[local.weekday()]
            when = f"{wd} {local.strftime('%d.%m, %H:%M')}"
            icon = "📝" if d.get("kind") == "exam" else "•"
            course = d.get("course_name") or ""
            tag = f"  [{course}]" if course else ""
            lines.append(f"  {icon} {rel} — {when}{tag}  {d['title']}")
        if len(deadlines) > max_deadlines:
            lines.append(f"  … und {len(deadlines) - max_deadlines} weitere")
    else:
        lines.append("  Keine Fristen in den nächsten 14 Tagen.")

    lines.append("")

    # --- new items ---------------------------------------------------------
    n = len(new_items)
    lines.append(f"🆕 Neu seit dem letzten Mal ({n}):")
    if new_items:
        for it in new_items[:max_new]:
            course = it["course_name"] if "course_name" in it.keys() else ""
            title = it["title"]
            lines.append(f"  • [{course}]  {title}")
        if n > max_new:
            lines.append(f"  … und {n - max_new} weitere")
    else:
        lines.append("  Keine neuen Materialien.")

    return "\n".join(lines)
