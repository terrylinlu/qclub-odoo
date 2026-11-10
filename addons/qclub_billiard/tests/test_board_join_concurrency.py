"""Real REPEATABLE READ race: stale snapshots must retry before counting."""
from contextlib import closing, contextmanager
from datetime import datetime, timedelta
from threading import Barrier, Thread
from uuid import uuid4
from zoneinfo import ZoneInfo

from psycopg2.errors import SerializationFailure

from odoo import SUPERUSER_ID, api
from odoo.exceptions import ValidationError
from odoo.orm.environments import Transaction
from odoo.sql_db import db_connect
from odoo.tests.common import TransactionCase, tagged
from odoo.tools import mute_logger


@tagged("post_install", "-at_install")
class TestBoardJoinConcurrency(TransactionCase):
    def test_brd_013_independent_transactions_accept_last_spot(self):
        registry = self.registry
        dbname = self.env.cr.dbname
        fixture = {}
        threads = []
        barrier = Barrier(2, timeout=5)
        results = {}
        retries = []
        suffix = uuid4().hex

        @contextmanager
        def connection():
            with closing(db_connect(dbname).cursor()) as cr:
                cr.execute("SET LOCAL lock_timeout = '5s'")
                cr.execute("SET LOCAL statement_timeout = '10s'")
                cr.transaction = Transaction(registry)
                yield cr

        def cleanup():
            barrier.abort()
            for thread in threads:
                thread.join(timeout=15)
            with connection() as cr:
                env = api.Environment(cr, SUPERUSER_ID, {})
                env["qclub.board.application"].search([("post_id", "in", fixture.get("post", []))]).unlink()
                env["qclub.board.post"].browse(fixture.get("post", [])).unlink()
                env["qclub.booking"].browse(fixture.get("booking", [])).unlink()
                env["qclub.table"].browse(fixture.get("table", [])).unlink()
                env["qclub.table.type"].browse(fixture.get("type", [])).unlink()
                env["res.partner"].browse(fixture.get("partners", [])).unlink()
                env["qclub.opening.hours"].browse(fixture.get("hours", [])).unlink()
                env["qclub.config"].browse(fixture.get("config", [])).unlink()
                env["ir.sequence.date_range"].browse(fixture.get("ranges", [])).unlink()
                cr.commit()
            self.assertFalse(any(thread.is_alive() for thread in threads))

        self.addCleanup(cleanup)
        with connection() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
            website = env["website"].search([("name", "=", "Q Club")], limit=1)
            self.assertTrue(website)
            if not env["qclub.config"].search_count([("website_id", "=", website.id)]):
                fixture["config"] = env["qclub.config"]._get_for_website(website).ids
            hours = env["qclub.opening.hours"]
            if not hours.search_count([("website_id", "=", website.id)]):
                fixture["hours"] = hours._load_default_hours(website).ids
            kind = env["qclub.table.type"].create({"name": suffix, "website_id": website.id})
            fixture["type"] = kind.ids
            table = env["qclub.table"].create({"name": suffix, "website_id": website.id,
                                               "type_id": kind.id, "hourly_price": 20})
            fixture["table"] = table.ids
            partners = env["res.partner"].create([{"name": "Race " + suffix + str(i)} for i in range(3)])
            fixture["partners"] = partners.ids
            owner = partners[0].id
            day = datetime.now(ZoneInfo("Australia/Adelaide")).date() + timedelta(days=2)
            intervals = hours._get_business_intervals(website, day)
            self.assertTrue(intervals)
            sequence = env.ref("qclub_billiard.qclub_booking_sequence")
            previous_ranges = sequence.date_range_ids
            sequence._get_current_sequence()
            fixture["ranges"] = (sequence.date_range_ids - previous_ranges).ids
            booking = env["qclub.booking"].create({"table_id": table.id, "partner_id": owner,
                                                     "start": intervals[0][0], "duration_hours": 1})
            fixture["booking"] = booking.ids
            booking.action_confirm()
            post = env["qclub.board.post"].create({"booking_id": booking.id, "message": "Race",
                                                  "players_needed": 1})
            fixture["post"] = post.ids
            applications = env["qclub.board.application"].create([
                {"post_id": post.id, "partner_id": partner.id} for partner in partners[1:]
            ]).ids
            cr.commit()

        def worker(index):
            try:
                for attempt in range(3):
                    try:
                        with connection() as cr:
                            env = api.Environment(cr, SUPERUSER_ID, {"lang": "en_US"})
                            application = env["qclub.board.application"].browse(applications[index])
                            # Establish the old snapshot in BOTH transactions before either update.
                            self.assertEqual(application.post_id._remaining(), 1 if attempt == 0 else 0)
                            if attempt == 0:
                                barrier.wait()
                            application._transition("accept", env["res.partner"].browse(owner))
                            cr.commit()
                        results[index] = "accepted"
                        return
                    except SerializationFailure:
                        retries.append(index)
                        # Fresh connection/Environment is the HTTP retry boundary.
                        continue
                    except ValidationError as error:
                        results[index] = str(error)
                        return
                results[index] = "retry exhausted"
            except BaseException as error:
                results[index] = repr(error)
                barrier.abort()

        with mute_logger("odoo.sql_db"):
            for index in range(2):
                thread = Thread(target=worker, args=(index,), daemon=True)
                threads.append(thread)
                thread.start()
            for thread in threads:
                thread.join(timeout=15)
        self.assertFalse(any(thread.is_alive() for thread in threads), repr(results))
        self.assertCountEqual(results.values(), ["accepted", "No spots left."])
        self.assertEqual(len(retries), 1, "The stale REPEATABLE READ snapshot must be retried")
        with connection() as cr:
            env = api.Environment(cr, SUPERUSER_ID, {})
            self.assertEqual(env["qclub.board.application"].search_count([
                ("post_id", "in", fixture["post"]), ("state", "=", "accepted"),
            ]), 1)
