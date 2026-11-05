from ast import literal_eval
from xml.etree import ElementTree

from freezegun import freeze_time

from odoo.tests.common import tagged

from .common import BilliardCase


@tagged("post_install", "-at_install")
class TestBookingList(BilliardCase):
    @freeze_time("2026-06-01 00:00:00")
    def test_adm_002_booked_on_views_and_creation(self):
        list_arch = ElementTree.fromstring(
            self.env.ref("qclub_billiard.qclub_booking_view_list").arch_db
        )
        columns = list(list_arch)
        name_index = next(i for i, node in enumerate(columns) if node.get("name") == "name")
        booked_on = columns[name_index + 1]
        self.assertEqual(booked_on.tag, "field")
        self.assertEqual(booked_on.get("name"), "create_date")
        self.assertEqual(booked_on.get("string"), "Booked On")

        form_arch = ElementTree.fromstring(
            self.env.ref("qclub_billiard.qclub_booking_view_form").arch_db
        )
        form_booked_on = form_arch.find(".//field[@name='create_date']")
        self.assertIsNotNone(form_booked_on)
        self.assertEqual(form_booked_on.get("string"), "Booked On")
        self.assertEqual(form_booked_on.get("readonly"), "True")
        self.assertEqual(form_booked_on.get("invisible"), "not create_date")

        search_arch = ElementTree.fromstring(
            self.env.ref("qclub_billiard.qclub_booking_view_search").arch_db
        )
        group = search_arch.find(".//group/filter[@name='group_create_date']")
        self.assertIsNotNone(group)
        self.assertEqual(group.get("string"), "Booked On")
        self.assertEqual(literal_eval(group.get("context")), {"group_by": "create_date:day"})

        hours = self.env["qclub.opening.hours"]
        hours.search([("website_id", "=", self.qclub.id)]).unlink()
        hours._load_default_hours(self.qclub)
        table = self.env["qclub.table"].create({
            "name": "Booked On test table",
            "type_id": self._make_type("Booked On test type").id,
            "website_id": self.qclub.id,
            "hourly_price": 25,
        })
        partner = self.env["res.partner"].create({"name": "Booked On test customer"})
        booking = self.env["qclub.booking"].with_user(self.staff).create({
            "table_id": table.id,
            "partner_id": partner.id,
            "start": "2026-06-01 04:30:00",
            "duration_hours": 1,
        })
        self.assertTrue(booking.create_date)
        self.assertNotEqual(booking.create_date, booking.start)
