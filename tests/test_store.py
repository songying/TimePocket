"""Domain regression tests for the SQLite store, with no external services."""
import math
import sys
import tempfile
import unittest
import uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from store import DEFAULTS, Store, week_bounds


def timestamp(value, zone="UTC"):
    return datetime.fromisoformat(value).replace(tzinfo=ZoneInfo(zone)).timestamp()


class StoreTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = str(Path(self.tmp.name) / "store.sqlite3")
        self.store = Store(self.path)
        self.uid = 1001
        self.now = timestamp("2026-09-30T12:00:00")
        self.week = "2026-09-28"
        state = self.store.state(self.uid, self.week)
        self.pid, self.other_pid = [p["id"] for p in state["projects"][:2]]

    def mutate(self, route, data, *, uid=None, now=None):
        return self.store.mutate(
            self.uid if uid is None else uid,
            route,
            data,
            now=self.now if now is None else now,
        )

    def state(self, week=None, uid=None):
        return self.store.state(self.uid if uid is None else uid, week or self.week)

    def project_state(self, pid=None, week=None):
        return next(p for p in self.state(week)["projects"] if p["id"] == (pid or self.pid))

    def manual_data(self, *, pid=None, start=None, minutes=30, request_id=None):
        return {
            "project_id": self.pid if pid is None else pid,
            "started_at": self.now - 7200 if start is None else start,
            "minutes": minutes,
            "request_id": str(uuid.uuid4()) if request_id is None else request_id,
        }

    def reminder(self, *, pid=None, due=None, label="Time for a break"):
        return self.mutate("reminders", {
            "project_id": self.pid if pid is None else pid,
            "due_at": self.now + 3600 if due is None else due,
            "label": label,
        })["id"]

    def reminder_state(self, rid):
        return next(r for r in self.state()["reminders"] if r["id"] == rid)

    def set_reminder_fields(self, rid, **fields):
        # Simulate worker-owned delivery states without involving a network worker.
        with self.store.db() as connection:
            assignments = ", ".join(f"{key}=?" for key in fields)
            connection.execute(
                f"UPDATE reminders SET {assignments} WHERE id=?",
                (*fields.values(), rid),
            )


class InitializationTests(StoreTestCase):
    def test_default_projects_are_created_once(self):
        first = self.state()
        second = self.state()
        self.assertEqual([(p["name"], p["budget_hours"]) for p in first["projects"]], DEFAULTS)
        self.assertEqual(first["projects"], second["projects"])
        self.assertEqual(first["timezone"], "UTC")
        self.assertEqual(first["total_budget"], 10)
        self.assertEqual(first["total_actual"], 0)
        self.assertIsNone(first["timer"])


class TimerTests(StoreTestCase):
    def test_repeated_start_returns_original_timer(self):
        first = self.mutate("timer/start", {"project_id": self.pid}, now=self.now - 1800)
        second = self.mutate("timer/start", {"project_id": self.pid})
        self.assertEqual(first["id"], second["id"])
        self.assertEqual(self.state()["timer"]["started_at"], self.now - 1800)
        self.assertEqual(len(self.state()["logs"]), 1)
        self.assertEqual(self.state()["total_actual"], 0)

    def test_different_project_cannot_start_while_timer_runs(self):
        first = self.mutate("timer/start", {"project_id": self.pid})
        with self.assertRaises(ValueError):
            self.mutate("timer/start", {"project_id": self.other_pid}, now=self.now + 60)
        self.assertEqual(self.state()["timer"]["id"], first["id"])
        self.assertEqual(len(self.state()["logs"]), 1)

    def test_stop_records_elapsed_time_and_notes_once(self):
        timer = self.mutate("timer/start", {"project_id": self.pid}, now=self.now - 1800)
        self.mutate("timer/stop", {
            "timer_id": timer["id"], "accomplishments": "Finished a lesson",
            "blockers": "None", "next_steps": "Review",
        })
        self.mutate("timer/stop", {"timer_id": timer["id"], "accomplishments": "Overwrite"}, now=self.now + 600)
        state = self.state()
        self.assertIsNone(state["timer"])
        self.assertEqual(state["total_actual"], 0.5)
        self.assertEqual(state["logs"][0]["ended_at"], self.now)
        self.assertEqual(state["logs"][0]["accomplishments"], "Finished a lesson")
        self.assertEqual(state["logs"][0]["blockers"], "None")
        self.assertEqual(state["logs"][0]["next_steps"], "Review")

    def test_stop_before_start_clamps_duration_to_zero(self):
        timer = self.mutate("timer/start", {"project_id": self.pid})
        self.mutate("timer/stop", {"timer_id": timer["id"]}, now=self.now - 60)
        log = self.state()["logs"][0]
        self.assertEqual(log["started_at"], log["ended_at"])
        self.assertEqual(self.state()["total_actual"], 0)

    def test_new_project_can_start_after_stop(self):
        first = self.mutate("timer/start", {"project_id": self.pid}, now=self.now - 1800)
        self.mutate("timer/stop", {"timer_id": first["id"]})
        second = self.mutate("timer/start", {"project_id": self.other_pid})
        self.assertNotEqual(first["id"], second["id"])
        self.assertEqual(self.state()["timer"]["project_id"], self.other_pid)

    def test_unknown_timer_cannot_be_stopped(self):
        with self.assertRaises(ValueError):
            self.mutate("timer/stop", {"timer_id": str(uuid.uuid4())})


class ManualLogTests(StoreTestCase):
    def test_manual_log_records_duration_and_notes(self):
        data = self.manual_data(minutes=45)
        data.update(accomplishments="Read", blockers="Noise", next_steps="Practice")
        result = self.mutate("logs", data)
        log = self.state()["logs"][0]
        self.assertEqual(log["id"], result["id"])
        self.assertEqual(log["ended_at"] - log["started_at"], 2700)
        self.assertEqual(log["request_id"], data["request_id"])
        self.assertEqual(log["accomplishments"], "Read")
        self.assertEqual(log["blockers"], "Noise")
        self.assertEqual(log["next_steps"], "Practice")
        self.assertEqual(self.state()["total_actual"], 0.75)

    def test_same_uuid_is_idempotent_even_on_retry_after_time_passes(self):
        data = self.manual_data()
        first = self.mutate("logs", data)
        second = self.mutate("logs", data, now=self.now + 60)
        self.assertEqual(first, second)
        self.assertEqual(len(self.state()["logs"]), 1)
        self.assertEqual(self.state()["total_actual"], 0.5)

    def test_duplicate_uuid_preserves_first_payload(self):
        data = self.manual_data()
        first = self.mutate("logs", data)
        retry = dict(data, started_at=self.now - 3600, minutes=15, accomplishments="Changed")
        self.assertEqual(self.mutate("logs", retry), first)
        log = self.state()["logs"][0]
        self.assertEqual(log["started_at"], data["started_at"])
        self.assertEqual(log["ended_at"] - log["started_at"], 1800)
        self.assertEqual(log["accomplishments"], "")

    def test_invalid_uuid_does_not_create_log(self):
        for rid in ("", "not-a-uuid", "1234"):
            with self.subTest(request_id=rid), self.assertRaises(ValueError):
                self.mutate("logs", self.manual_data(request_id=rid))
        self.assertEqual(self.state()["logs"], [])

    def test_manual_overlap_is_rejected_across_projects(self):
        start = self.now - 7200
        self.mutate("logs", self.manual_data(start=start, minutes=60))
        for offset, minutes in ((0, 60), (-60, 2), (3599, 2), (60, 10), (-60, 62)):
            with self.subTest(offset=offset, minutes=minutes), self.assertRaises(ValueError):
                self.mutate("logs", self.manual_data(pid=self.other_pid, start=start + offset, minutes=minutes))
        self.assertEqual(len(self.state()["logs"]), 1)

    def test_adjacent_manual_logs_are_not_overlaps(self):
        start = self.now - 7200
        self.mutate("logs", self.manual_data(start=start, minutes=30))
        self.mutate("logs", self.manual_data(pid=self.other_pid, start=start - 1800, minutes=30))
        self.mutate("logs", self.manual_data(pid=self.other_pid, start=start + 1800, minutes=30))
        self.assertEqual(len(self.state()["logs"]), 3)
        self.assertEqual(self.state()["total_actual"], 1.5)

    def test_manual_overlap_with_active_timer_is_rejected(self):
        self.mutate("timer/start", {"project_id": self.pid}, now=self.now - 3600)
        with self.assertRaises(ValueError):
            self.mutate("logs", self.manual_data(pid=self.other_pid, start=self.now - 4000, minutes=30))
        with self.assertRaises(ValueError):
            self.mutate("logs", self.manual_data(pid=self.other_pid, start=self.now - 1800, minutes=15))
        self.assertEqual(len(self.state()["logs"]), 1)

    def test_manual_log_ending_exactly_at_active_timer_start_is_allowed(self):
        self.mutate("timer/start", {"project_id": self.pid}, now=self.now - 3600)
        self.mutate("logs", self.manual_data(start=self.now - 5400, minutes=30))
        self.assertEqual(len(self.state()["logs"]), 2)
        self.assertEqual(self.state()["total_actual"], 0.5)

    def test_invalid_durations_and_nonfinite_timestamps_are_rejected(self):
        cases = [{"minutes": value} for value in (0, -1, 1441, math.nan, math.inf, -math.inf)]
        cases += [{"started_at": value} for value in (-1, math.nan, math.inf, -math.inf)]
        cases += [{"started_at": self.now - 30, "minutes": 1}]
        for changes in cases:
            data = self.manual_data()
            data.update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                self.mutate("logs", data)
        self.assertEqual(self.state()["logs"], [])


class BudgetTests(StoreTestCase):
    def test_invalid_budget_preserves_existing_project_and_budget(self):
        before = self.project_state()
        for budget in (math.nan, math.inf, -math.inf, "NaN", -0.01, 168.01):
            with self.subTest(budget=budget), self.assertRaises(ValueError):
                self.mutate("projects", {"id": self.pid, "name": "Should roll back", "budget_hours": budget, "week": self.week})
            self.assertEqual(self.project_state(), before)

    def test_budget_endpoints_are_allowed(self):
        for budget in (0, 168):
            with self.subTest(budget=budget):
                self.mutate("projects", {"id": self.pid, "budget_hours": budget, "week": self.week})
                self.assertEqual(self.project_state()["budget_hours"], budget)

    def test_week_budget_survives_edits_to_other_weeks_and_reopen(self):
        next_week = "2026-10-05"
        self.mutate("projects", {"id": self.pid, "budget_hours": 4.25, "week": self.week})
        self.mutate("projects", {"id": self.pid, "budget_hours": 6, "week": next_week})
        self.store = Store(self.path)
        self.assertEqual(self.project_state(week=self.week)["budget_hours"], 4.25)
        self.assertEqual(self.project_state(week=next_week)["budget_hours"], 6)
        self.assertEqual(self.project_state(week="2026-10-12")["budget_hours"], 6)

    def test_existing_week_snapshot_is_unchanged_when_default_changes(self):
        initial = self.project_state()["budget_hours"]
        self.mutate("projects", {"id": self.pid, "budget_hours": 9, "week": "2026-10-05"})
        self.assertEqual(self.project_state()["budget_hours"], initial)

    def test_budget_week_dates_normalize_to_local_monday(self):
        self.mutate("projects", {"id": self.pid, "budget_hours": 7, "week": "2026-10-04"})
        self.assertEqual(self.project_state(week="2026-09-28")["budget_hours"], 7)
        self.assertEqual(self.state("2026-10-04")["week"], "2026-09-28")


class CalendarTests(StoreTestCase):
    def test_local_sunday_and_monday_are_in_different_weeks(self):
        sunday = timestamp("2026-10-04T23:59:59", "Asia/Shanghai")
        monday = timestamp("2026-10-05T00:00:00", "Asia/Shanghai")
        self.assertEqual(week_bounds("Asia/Shanghai", now=sunday)[0], "2026-09-28")
        self.assertEqual(week_bounds("Asia/Shanghai", now=monday)[0], "2026-10-05")
        self.assertEqual(week_bounds("UTC", now=monday)[0], "2026-09-28")

    def test_log_crossing_local_week_boundary_is_split(self):
        zone = "America/New_York"
        self.mutate("settings", {"timezone": zone})
        start = timestamp("2026-09-27T23:30:00", zone)
        self.mutate("logs", self.manual_data(start=start, minutes=90))
        self.assertEqual(self.project_state(week="2026-09-21")["actual_hours"], 0.5)
        self.assertEqual(self.project_state(week="2026-09-28")["actual_hours"], 1)
        self.assertEqual(len(self.state("2026-09-21")["logs"]), 1)
        self.assertEqual(len(self.state("2026-09-28")["logs"]), 1)

    def test_log_on_monday_boundary_does_not_leak_into_previous_week(self):
        self.mutate("settings", {"timezone": "Asia/Shanghai"})
        start = timestamp("2026-09-28T00:00:00", "Asia/Shanghai")
        self.mutate("logs", self.manual_data(start=start, minutes=30))
        self.assertEqual(self.state("2026-09-21")["logs"], [])
        self.assertEqual(self.state("2026-09-21")["total_actual"], 0)
        self.assertEqual(self.state()["total_actual"], 0.5)

    def test_log_ending_on_monday_boundary_does_not_leak_into_next_week(self):
        self.mutate("settings", {"timezone": "Asia/Shanghai"})
        end = timestamp("2026-09-28T00:00:00", "Asia/Shanghai")
        self.mutate("logs", self.manual_data(start=end - 1800, minutes=30))
        self.assertEqual(self.state()["logs"], [])
        self.assertEqual(self.state()["total_actual"], 0)
        self.assertEqual(self.state("2026-09-21")["total_actual"], 0.5)

    def test_dst_weeks_have_167_and_169_elapsed_hours(self):
        for day, expected in (("2026-03-02", 167), ("2026-10-26", 169)):
            with self.subTest(day=day):
                week, start, end = week_bounds("America/New_York", day)
                self.assertEqual(week, day)
                self.assertEqual((end - start) / 3600, expected)
                self.assertEqual(datetime.fromtimestamp(start, ZoneInfo("America/New_York")).hour, 0)
                self.assertEqual(datetime.fromtimestamp(end, ZoneInfo("America/New_York")).hour, 0)
                self.assertEqual((week_bounds("UTC", day)[2] - week_bounds("UTC", day)[1]) / 3600, 168)

    def test_totals_clip_timer_to_actual_dst_week_length(self):
        self.mutate("settings", {"timezone": "America/New_York"})
        for day, expected in (("2026-03-02", 167), ("2026-10-26", 169)):
            with self.subTest(day=day):
                _, start, end = week_bounds("America/New_York", day)
                timer = self.mutate("timer/start", {"project_id": self.pid}, now=start - 3600)
                self.mutate("timer/stop", {"timer_id": timer["id"]}, now=end + 3600)
                self.assertEqual(self.state(day)["total_actual"], expected)


class OwnershipTests(StoreTestCase):
    def setUp(self):
        super().setUp()
        self.other_uid = 2002
        self.foreign_pid = self.state(uid=self.other_uid)["projects"][0]["id"]

    def test_users_cannot_mutate_other_users_projects(self):
        actions = (
            ("projects", {"id": self.foreign_pid, "budget_hours": 1, "week": self.week}),
            ("timer/start", {"project_id": self.foreign_pid}),
            ("logs", self.manual_data(pid=self.foreign_pid)),
            ("reminders", {"project_id": self.foreign_pid, "due_at": self.now + 60}),
        )
        for route, data in actions:
            with self.subTest(route=route), self.assertRaises(ValueError):
                self.mutate(route, data)
        self.assertEqual(self.state()["logs"], [])
        self.assertEqual(self.state()["reminders"], [])
        self.assertEqual(self.state(uid=self.other_uid)["projects"][0]["budget_hours"], DEFAULTS[0][1])

    def test_timer_ownership_is_enforced(self):
        timer = self.mutate("timer/start", {"project_id": self.pid})
        with self.assertRaises(ValueError):
            self.mutate("timer/stop", {"timer_id": timer["id"]}, uid=self.other_uid)
        self.assertEqual(self.state()["timer"]["id"], timer["id"])
        self.assertIsNone(self.state(uid=self.other_uid)["timer"])

    def test_reminder_ownership_is_enforced_for_snooze_and_skip(self):
        rid = self.reminder()
        for action in ("snooze", "skip"):
            with self.subTest(action=action), self.assertRaises(ValueError):
                self.mutate("reminders/action", {"id": rid, "action": action}, uid=self.other_uid)
        self.assertEqual(self.reminder_state(rid)["status"], "pending")
        self.assertEqual(self.state(uid=self.other_uid)["reminders"], [])

    def test_users_can_have_concurrent_timers(self):
        first = self.mutate("timer/start", {"project_id": self.pid})
        second = self.mutate("timer/start", {"project_id": self.foreign_pid}, uid=self.other_uid)
        self.assertNotEqual(first["id"], second["id"])
        self.assertEqual(self.state()["timer"]["id"], first["id"])
        self.assertEqual(self.state(uid=self.other_uid)["timer"]["id"], second["id"])

    def test_uuid_and_overlap_checks_are_scoped_to_user(self):
        data = self.manual_data()
        first = self.mutate("logs", data)
        second = self.mutate("logs", dict(data, project_id=self.foreign_pid), uid=self.other_uid)
        self.assertNotEqual(first["id"], second["id"])
        self.assertEqual(len(self.state()["logs"]), 1)
        self.assertEqual(len(self.state(uid=self.other_uid)["logs"]), 1)


class ReminderTests(StoreTestCase):
    def test_repeated_identical_pending_reminders_are_deduplicated(self):
        ids = [self.reminder() for _ in range(3)]
        self.assertEqual(len(set(ids)), 1)
        self.assertEqual(len(self.state()["reminders"]), 1)

    def test_distinct_project_time_or_label_creates_distinct_reminder(self):
        ids = {
            self.reminder(),
            self.reminder(pid=self.other_pid),
            self.reminder(due=self.now + 3601),
            self.reminder(label="A different reminder"),
        }
        self.assertEqual(len(ids), 4)

    def test_snooze_defaults_to_fifteen_minutes_and_resets_delivery_retry(self):
        rid = self.reminder()
        self.set_reminder_fields(rid, status="sent", attempts=3, next_try=self.now + 10, last_error="offline")
        self.mutate("reminders/action", {"id": rid, "action": "snooze"})
        reminder = self.reminder_state(rid)
        self.assertEqual(reminder["status"], "pending")
        self.assertEqual(reminder["due_at"], self.now + 900)
        self.assertEqual(reminder["attempts"], 0)
        self.assertEqual(reminder["next_try"], 0)
        self.assertEqual(reminder["last_error"], "")

    def test_snooze_uses_requested_duration(self):
        rid = self.reminder()
        self.mutate("reminders/action", {"id": rid, "action": "snooze", "minutes": 60})
        self.assertEqual(self.reminder_state(rid)["due_at"], self.now + 3600)

    def test_skip_is_idempotent_and_prevents_snooze(self):
        rid = self.reminder()
        for _ in range(2):
            self.mutate("reminders/action", {"id": rid, "action": "skip"})
        self.assertEqual(self.reminder_state(rid)["status"], "skipped")
        with self.assertRaises(ValueError):
            self.mutate("reminders/action", {"id": rid, "action": "snooze"})
        self.assertEqual(self.reminder_state(rid)["status"], "skipped")

    def test_skipped_reminder_does_not_block_new_identical_schedule(self):
        first = self.reminder()
        self.mutate("reminders/action", {"id": first, "action": "skip"})
        second = self.reminder()
        self.assertNotEqual(first, second)
        self.assertEqual(self.reminder_state(second)["status"], "pending")

    def test_expired_reminder_cannot_be_snoozed(self):
        rid = self.reminder()
        self.set_reminder_fields(rid, status="expired")
        with self.assertRaises(ValueError):
            self.mutate("reminders/action", {"id": rid, "action": "snooze"})
        self.assertEqual(self.reminder_state(rid)["status"], "expired")

    def test_delivering_reminder_cannot_be_snoozed_or_skipped(self):
        rid = self.reminder()
        self.set_reminder_fields(rid, status="delivering")
        for action in ("snooze", "skip"):
            with self.subTest(action=action), self.assertRaises(ValueError):
                self.mutate("reminders/action", {"id": rid, "action": action})
        self.assertEqual(self.reminder_state(rid)["status"], "delivering")

    def test_invalid_due_times_are_rejected(self):
        for due in (math.nan, math.inf, -math.inf, self.now - 61, self.now + 366 * 86400 + 1):
            with self.subTest(due=due), self.assertRaises(ValueError):
                self.reminder(due=due)
        self.assertEqual(self.state()["reminders"], [])

    def test_invalid_snooze_does_not_modify_schedule(self):
        rid = self.reminder()
        before = self.reminder_state(rid)
        for minutes in (0, -1, 1441, math.nan, math.inf):
            with self.subTest(minutes=minutes), self.assertRaises(ValueError):
                self.mutate("reminders/action", {"id": rid, "action": "snooze", "minutes": minutes})
            self.assertEqual(self.reminder_state(rid), before)

    def test_unknown_action_and_unknown_reminder_are_rejected(self):
        rid = self.reminder()
        with self.assertRaises(ValueError):
            self.mutate("reminders/action", {"id": rid, "action": "erase"})
        with self.assertRaises(ValueError):
            self.mutate("reminders/action", {"id": str(uuid.uuid4()), "action": "skip"})
        self.assertEqual(self.reminder_state(rid)["status"], "pending")


if __name__ == "__main__":
    unittest.main()
