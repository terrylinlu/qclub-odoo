import logging
import time
import traceback
from contextlib import closing, contextmanager
from datetime import datetime, timedelta, timezone
from threading import Barrier, Event, Lock, Thread
from unittest.mock import patch
from uuid import uuid4
from zoneinfo import ZoneInfo

from freezegun import freeze_time
from psycopg2.errors import ExclusionViolation

from odoo import SUPERUSER_ID, api
from odoo.exceptions import ValidationError
from odoo.orm.environments import Transaction
from odoo.sql_db import db_connect
from odoo.tests.common import TransactionCase, tagged
from odoo.tools import mute_logger

from .common import BilliardCase

_logger = logging.getLogger(__name__)

FRIENDLY = "This table is already booked for the selected time. Please choose another time or table."
TZ = ZoneInfo("Australia/Adelaide")


@tagged("post_install", "-at_install")
@freeze_time("2026-06-01 00:00:00")
class TestBookingConstraint(BilliardCase):
    def setUp(self):
        super().setUp()
        self.Booking = self.env["qclub.booking"].with_context(lang="en_US")
        hours = self.env["qclub.opening.hours"]
        hours.search([("website_id", "=", self.qclub.id)]).unlink()
        hours._load_default_hours(self.qclub)
        self.env["qclub.config"]._get_for_website(self.qclub).write({
            "lock_minutes": 10, "max_advance_days": 14, "max_consecutive_hours": 4,
        })
        kind = self._make_type("Exclusion test type")
        self.table, self.other = self.env["qclub.table"].create([
            {"name": name, "type_id": kind.id, "website_id": self.qclub.id, "hourly_price": 25}
            for name in ("Exclusion A", "Exclusion B")
        ])

    def _book(self, **values):
        return self.Booking.create({
            "table_id": self.table.id, "partner_id": self.env.user.partner_id.id,
            "start": "2026-06-01 05:30:00", "duration_hours": 2, **values,
        })

    def _sql_move(self, booking, start="2026-06-01 06:30:00", end="2026-06-01 08:30:00"):
        self.env.flush_all()
        self.env.cr.execute(
            'UPDATE qclub_booking SET start=%s, "end"=%s WHERE id=%s', (start, end, booking.id),
        )
        booking.invalidate_recordset()

    def test_bk_004_constraint_exists_and_rejects_sql_overlap(self):
        self.env.cr.execute(
            "SELECT contype FROM pg_constraint WHERE conname=%s AND conrelid='qclub_booking'::regclass",
            ("qclub_booking_no_overlap",),
        )
        self.assertEqual(self.env.cr.fetchall(), [("x",)])
        self._book()
        second = self._book(start="2026-06-01 09:30:00")
        with self.assertRaises(ExclusionViolation), mute_logger("odoo.sql_db"), self.env.cr.savepoint():
            self._sql_move(second)

    def test_bk_004_insert_before_existing_later_booking_has_bounded_end(self):
        later = self._book(start="2026-06-15 04:30:00", duration_hours=1)
        earlier = self._book(
            start="2026-06-05 15:30:00", duration_hours=1,
            end="2099-01-01 00:00:00",  # Never trust a client-supplied derived field.
        )
        self.env.cr.execute(
            'SELECT id, "end" FROM qclub_booking WHERE id IN %s ORDER BY id',
            (tuple((later | earlier).ids),),
        )
        self.assertEqual(self.env.cr.fetchall(), [
            (later.id, datetime(2026, 6, 15, 5, 30)),
            (earlier.id, datetime(2026, 6, 5, 16, 30)),
        ])

    def test_bk_004_init_repairs_different_constraint_and_is_idempotent(self):
        # DDL is rolled back with this test's savepoint; merged tests are unaffected.
        self.env.cr.execute("ALTER TABLE qclub_booking DROP CONSTRAINT qclub_booking_no_overlap")
        self.env.cr.execute("""
            ALTER TABLE qclub_booking ADD CONSTRAINT qclub_booking_no_overlap
            EXCLUDE USING gist (table_id WITH =, tsrange(start, "end", '[)') WITH &&)
            WHERE (state = 'pending')
        """)
        self.Booking.init()
        self.env.cr.execute(
            "SELECT oid FROM pg_constraint WHERE conname=%s AND conrelid='qclub_booking'::regclass",
            ("qclub_booking_no_overlap",),
        )
        oid = self.env.cr.fetchone()[0]
        self.Booking.init()
        self.env.cr.execute(
            "SELECT oid FROM pg_constraint WHERE conname=%s AND conrelid='qclub_booking'::regclass",
            ("qclub_booking_no_overlap",),
        )
        self.assertEqual(self.env.cr.fetchone()[0], oid)
        first = self._book()
        first.action_confirm()
        second = self._book(start="2026-06-01 09:30:00")
        second.action_confirm()
        with self.assertRaises(ExclusionViolation), mute_logger("odoo.sql_db"), self.env.cr.savepoint():
            self._sql_move(second)

    def test_bk_004_cancelled_overlap_allowed(self):
        self._book()
        second = self._book(start="2026-06-01 09:30:00")
        second.action_cancel()
        self._sql_move(second)
        self.assertEqual(second.state, "cancelled")

    def test_bk_004_adjacent_and_other_table_allowed(self):
        self._book()  # Adelaide 15:00–17:00
        adjacent = self._book(start="2026-06-01 09:30:00")
        self._sql_move(adjacent, "2026-06-01 07:30:00", "2026-06-01 09:30:00")
        other = self._book(table_id=self.other.id, start="2026-06-01 09:30:00")
        self._sql_move(other)
        self.assertEqual(adjacent.start, datetime(2026, 6, 1, 7, 30))
        self.assertEqual(other.start, datetime(2026, 6, 1, 6, 30))

    def _assert_friendly(self, operation):
        with patch.object(type(self.Booking), "_check_conflicts", lambda self: None):
            with self.assertRaises(ValidationError) as caught, mute_logger("odoo.sql_db"):
                operation()
        message = str(caught.exception)
        self.assertEqual(message, FRIENDLY)
        self.assertNotIn("qclub_booking_no_overlap", message)
        self.assertNotIn("violates", message)
        # The exception must leave the caller's transaction usable.
        self.assertEqual(self.Booking.search_count([("table_id", "=", self.table.id)]), 2)

    def test_adm_003_database_create_friendly(self):
        self._book()
        self._book(start="2026-06-01 09:30:00")
        self._assert_friendly(lambda: self._book())
        self._book(table_id=self.other.id)

    def test_adm_003_database_write_friendly(self):
        self._book()
        second = self._book(start="2026-06-01 09:30:00")
        self._assert_friendly(lambda: second.write({"start": "2026-06-01 06:30:00"}))
        self.assertEqual(second.start, datetime(2026, 6, 1, 9, 30))

    def test_bk_008_cron_expiry_and_slot_reuse(self):
        stale = self._book()
        confirmed = self._book(table_id=self.other.id)
        confirmed.action_confirm()
        with freeze_time("2026-06-01 00:05:00"):
            fresh = self._book(start="2026-06-01 09:30:00")
        with freeze_time("2026-06-01 00:10:00"):
            expired = self.Booking._cron_expire_pending()
            self.assertIn(stale, expired)
            self.assertNotIn(fresh, expired)
            self.assertEqual(stale.state, "expired")
            self.assertEqual(fresh.state, "pending")
            self.assertEqual(confirmed.state, "confirmed")
            self._book()

    def test_bk_008_on_demand_create_and_write(self):
        stale = self._book()
        moving = self._book(table_id=self.other.id, start="2026-06-01 09:30:00")
        moving.action_confirm()
        with freeze_time("2026-06-01 00:10:00"):
            replacement = self._book()
            self.assertEqual(stale.state, "expired")
            replacement.action_cancel()
            stale_again = self._book()
        with freeze_time("2026-06-01 00:20:00"):
            moving.write({"table_id": self.table.id, "start": stale_again.start})
            self.assertEqual(stale_again.state, "expired")
            self.assertEqual(moving.state, "confirmed")

    def test_bk_008_cron_continues_after_one_failure(self):
        failing = self._book()
        succeeding = self._book(table_id=self.other.id)
        original = type(self.Booking)._action_expire

        def expire(booking):
            if booking.id == failing.id:
                # Change first, then fail: the per-record savepoint must undo it.
                original(booking)
                raise ValidationError("Simulated expiry failure")
            return original(booking)

        with freeze_time("2026-06-01 00:10:00"):
            with patch.object(type(self.Booking), "_action_expire", expire):
                with mute_logger("odoo.addons.qclub_billiard.models.qclub_booking"):
                    expired = self.Booking._cron_expire_pending()
        self.assertNotIn(failing, expired)
        self.assertIn(succeeding, expired)
        self.assertEqual(failing.state, "pending")
        self.assertEqual(succeeding.state, "expired")

    def test_bk_008_adelaide_dst_overnight_expiry(self):
        cases = (
            ("2026-04-03 00:00:00", datetime(2026, 4, 5, 0, tzinfo=TZ)),
            ("2026-10-02 00:00:00", datetime(2026, 10, 3, 23, tzinfo=TZ)),
        )
        for now, local_start in cases:
            with self.subTest(local_start=local_start), freeze_time(now) as clock:
                start = local_start.astimezone(timezone.utc).replace(tzinfo=None)
                stale = self._book(start=start, duration_hours=1)
                self.assertEqual(stale.business_date, (local_start - timedelta(days=1)).date()
                                 if local_start.hour == 0 else local_start.date())
                clock.tick(delta=timedelta(minutes=10))
                self.assertIn(stale, self.Booking._cron_expire_pending())
                self.assertEqual(stale.state, "expired")
                replacement = self._book(start=start, duration_hours=1)
                self.assertEqual(replacement.state, "pending")
                replacement.action_cancel()

    def test_bk_008_on_demand_cannot_revive_expired_booking(self):
        stale = self._book()
        with freeze_time("2026-06-01 00:10:00"):
            with self.assertRaises(ValidationError):
                stale.write({"start": "2026-06-01 09:30:00", "state": "confirmed"})
            # Failed write rolls back its on-demand expiry as well.
            self.assertEqual(stale.state, "pending")
            self.Booking._cron_expire_pending()
            self.assertEqual(stale.state, "expired")

    def test_bk_008_cron_configuration(self):
        cron = self.env.ref("qclub_billiard.qclub_booking_cron_expire_pending")
        self.assertTrue(cron.active)
        self.assertEqual((cron.interval_number, cron.interval_type), (1, "minutes"))
        self.assertEqual(cron.model_id.model, "qclub.booking")
        self.assertEqual(cron.code, "model._cron_expire_pending()")


@tagged("post_install", "-at_install")
class TestBookingConcurrency(TransactionCase):
    def test_bk_005_adm_003_independent_transactions(self):
        self._run_booking_races(rounds=5)

    def test_bk_005_different_tables_do_not_block_each_other(self):
        self._run_booking_races(rounds=1, different_tables=True)

    def _run_booking_races(self, rounds, different_tables=False):
        # This class creates no fixture data on the TransactionCase cursor.
        started = time.monotonic()
        dbname = self.env.cr.dbname
        registry = self.registry
        fixture = {}
        threads = []
        worker_info = {}
        results = {}
        errors = {}
        guard = Lock()
        stop = Event()
        barrier = Barrier(2, timeout=5)
        suffix = uuid4().hex
        application_names = tuple("qclub-concurrency-" + suffix + "-" + str(i) for i in range(2))

        @contextmanager
        def connection(worker_index=None):
            with closing(db_connect(dbname).cursor()) as cr:
                # Record the backend before any SQL or Environment construction.
                if worker_index is not None:
                    with guard:
                        worker_info[worker_index] = {"pid": cr._cnx.get_backend_pid(), "stage": "connected"}
                cr.execute("SET LOCAL lock_timeout = '10s'")
                cr.execute("SET LOCAL statement_timeout = '30s'")
                if worker_index is not None:
                    cr.execute("SELECT set_config('application_name', %s, true)", (application_names[worker_index],))
                # Environment(cr, ...) otherwise calls Registry(dbname), whose
                # global RLock may be held by the module-loading/test thread.
                # Share only the registry, never another cursor's transaction/cache.
                cr.transaction = Transaction(registry)
                yield cr

        def diagnostics():
            with connection() as cr:
                cr.execute("""
                    SELECT pid, state, wait_event_type, wait_event, query
                    FROM pg_stat_activity WHERE datname = current_database() ORDER BY pid
                """)
                activity = cr.dictfetchall()
            with guard:
                report = {"workers": dict(worker_info), "exceptions": dict(errors), "activity": activity}
            _logger.error("Concurrent booking timeout diagnostics: %s", report)
            return report

        def cleanup():
            stop.set()
            barrier.abort()
            try:
                # Never wait for workers before removing their database locks.
                with connection() as cr:
                    with guard:
                        pids = tuple(info["pid"] for info in worker_info.values())
                    if pids:
                        cr.execute("""
                            SELECT pg_terminate_backend(pid)
                            FROM pg_stat_activity
                            WHERE datname = current_database() AND pid IN %s AND application_name IN %s
                        """, (pids, application_names))
            finally:
                # Cleanup is independent of worker completion, including Python-side hangs.
                with connection() as cr:
                    env = api.Environment(cr, SUPERUSER_ID, {})
                    if fixture.get("tables"):
                        env["qclub.booking"].search([("table_id", "in", fixture["tables"])]).unlink()
                        env["qclub.table"].browse(fixture["tables"]).exists().unlink()
                    if fixture.get("type"):
                        env["qclub.table.type"].browse(fixture["type"]).exists().unlink()
                    env["qclub.opening.hours"].browse(fixture.get("hours", [])).exists().unlink()
                    env["qclub.config"].browse(fixture.get("config", [])).exists().unlink()
                    env["ir.sequence.date_range"].browse(fixture.get("sequence_ranges", [])).exists().unlink()
                    cr.commit()
            # Only after committing cleanup do we check that Python workers exited.
            for thread in threads:
                thread.join(timeout=5)
            self.assertFalse(
                any(thread.is_alive() for thread in threads),
                "Worker still alive after backend termination: " + repr((worker_info, errors)),
            )

        self.addCleanup(cleanup)
        with connection() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
            website = env["website"].search([("name", "=", "Q Club")], limit=1)
            self.assertTrue(website)
            config = env["qclub.config"].search([("website_id", "=", website.id)], limit=1)
            if not config:
                config = env["qclub.config"]._get_for_website(website)
                fixture["config"] = config.ids
            hours = env["qclub.opening.hours"]
            if not hours.search_count([("website_id", "=", website.id)]):
                fixture["hours"] = hours.create([
                    {"website_id": website.id, "weekday": str(day), "open_hour": 0, "close_hour": 24}
                    for day in range(7)
                ]).ids
            kind = env["qclub.table.type"].create({
                "name": "Concurrency Type " + suffix, "website_id": website.id,
            })
            fixture["type"] = kind.id
            tables = env["qclub.table"].create([
                {
                    "name": "Concurrency Table " + suffix + "-" + str(index), "type_id": kind.id,
                    "website_id": website.id, "hourly_price": 25,
                }
                for index in range(2 if different_tables else 1)
            ])
            fixture["tables"] = tables.ids
            slot_starts = []
            for round_index in range(rounds):
                day = datetime.now(TZ).date() + timedelta(days=2 + round_index)
                intervals = hours._get_business_intervals(website, day)
                candidates = [start for start, stop_time in intervals if start + timedelta(hours=2) <= stop_time]
                self.assertTrue(candidates, "Committed opening hours need a two-hour slot on " + str(day))
                slot_starts.append(candidates[0])
            partner_id = env.user.partner_id.id
            # next_by_code uses date ranges. Create/commit the current range before
            # the race so both workers use the real, same PostgreSQL sequence.
            sequence = env.ref("qclub_billiard.qclub_booking_sequence")
            previous_ranges = sequence.date_range_ids
            sequence._get_current_sequence()
            fixture["sequence_ranges"] = (sequence.date_range_ids - previous_ranges).ids
            cr.commit()

        def stage(index, value):
            with guard:
                worker_info[index]["stage"] = value

        def worker(index):
            try:
                with connection(index) as cr:
                    env = api.Environment(cr, SUPERUSER_ID, {"lang": "en_US"})
                    stage(index, "barrier")
                    barrier.wait(timeout=5)
                    if stop.is_set():
                        raise RuntimeError("Concurrent booking test stopped")
                    stage(index, "create")
                    values = {
                        "table_id": fixture["tables"][index if different_tables else 0],
                        "partner_id": partner_id, "start": slot_start, "duration_hours": 2,
                    }
                    env["qclub.booking"].create(values)
                    if different_tables:
                        # Both INSERTs must finish while neither transaction has
                        # committed: even a global lock that eventually lets both
                        # succeed must fail this test.
                        stage(index, "both inserted before commit")
                        barrier.wait(timeout=5)
                    if stop.is_set():
                        raise RuntimeError("Concurrent booking test stopped before commit")
                    stage(index, "commit")
                    cr.commit()
                with guard:
                    results[index] = None
                    worker_info[index]["stage"] = "closed"
            except BaseException as error:
                # Include failures before the barrier and connection/close failures.
                with guard:
                    results[index] = error
                    errors[index] = traceback.format_exc()
                barrier.abort()

        for round_index, slot_start in enumerate(slot_starts):
            barrier = Barrier(2, timeout=5)
            results.clear()
            errors.clear()
            with mute_logger("odoo.sql_db"):
                round_threads = []
                for index in range(2):
                    thread = Thread(target=worker, args=(index,), name=application_names[index], daemon=True)
                    threads.append(thread)
                    round_threads.append(thread)
                    thread.start()
                # One budget across all rounds, rather than 45 seconds per round.
                deadline = started + 25
                for thread in round_threads:
                    thread.join(timeout=max(0, deadline - time.monotonic()))
            if any(thread.is_alive() for thread in round_threads):
                report = diagnostics()
                self.fail("Concurrent booking timed out: " + repr(report))
            detail = repr((round_index, results, errors, worker_info))
            expected_successes = 2 if different_tables else 1
            unexpected = (
                len(results) != 2
                or list(results.values()).count(None) != expected_successes
                or any(result is not None and not isinstance(result, ValidationError) for result in results.values())
            )
            if unexpected:
                detail += repr(diagnostics())
            # Assertions deliberately stop the loop on failure, preserving the
            # failing round's backend IDs and exceptions for addCleanup.
            self.assertEqual(len(results), 2, detail)
            self.assertEqual(list(results.values()).count(None), expected_successes, detail)
            if not different_tables:
                failures = [result for result in results.values() if result is not None]
                self.assertIsInstance(failures[0], ValidationError, detail)
                self.assertEqual(str(failures[0]), FRIENDLY, detail)
            with connection() as cr:
                env = api.Environment(cr, SUPERUSER_ID, {})
                bookings = env["qclub.booking"].search([("table_id", "in", fixture["tables"])])
                self.assertEqual(len(bookings), expected_successes, detail)
                self.assertEqual(set(bookings.mapped("start")), {slot_start})
                bookings.unlink()
                cr.commit()
        self.assertLess(time.monotonic() - started, 30, "Booking races exceeded the runtime budget")
