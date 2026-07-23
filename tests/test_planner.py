"""Daily planner: quota seeding, daily reset, toggle, free-time math."""
from app.db import init_db, get_session
from app.db.models import DailyTask
from app import planner


def _reset():
    init_db()
    with get_session() as s:
        s.query(DailyTask).delete()


def test_ensure_day_seeds_quotas_once():
    _reset()
    planner.ensure_day("2026-07-23")
    with get_session() as s:
        n = s.query(DailyTask).filter_by(day="2026-07-23").count()
    assert n == 6 + 7 + 3 + 1  # tiktok+skool+substack+youtube
    planner.ensure_day("2026-07-23")  # idempotent
    with get_session() as s:
        assert s.query(DailyTask).filter_by(day="2026-07-23").count() == 17


def test_plan_structure_and_counts():
    _reset()
    p = planner.plan("2026-07-23")
    kinds = {q["kind"]: q["total"] for q in p["quotas"]}
    assert kinds == {"tiktok": 6, "skool": 7, "substack": 3, "youtube": 1}
    assert all(q["done"] == 0 for q in p["quotas"])


def test_toggle_marks_done():
    _reset()
    p = planner.plan("2026-07-23")
    tid = p["quotas"][0]["tasks"][0]["id"]
    assert planner.toggle(tid) is True
    p2 = planner.plan("2026-07-23")
    done = sum(q["done"] for q in p2["quotas"])
    assert done == 1
    assert planner.toggle(tid) is False  # toggles back


def test_daily_reset_is_per_day():
    _reset()
    planner.ensure_day("2026-07-23")
    p = planner.plan("2026-07-23")
    planner.toggle(p["quotas"][0]["tasks"][0]["id"])
    # a new day seeds fresh, all undone
    p2 = planner.plan("2026-07-24")
    assert sum(q["done"] for q in p2["quotas"]) == 0
    assert p2["day"] == "2026-07-24"


def test_free_slots_between_events():
    sched = [{"minute": 10 * 60}, {"minute": 14 * 60}]  # 10:00 and 14:00 (each ~1h)
    free = planner.free_slots(sched)
    assert "08:00–10:00" in free
    assert "11:00–14:00" in free
    assert "15:00–20:00" in free
