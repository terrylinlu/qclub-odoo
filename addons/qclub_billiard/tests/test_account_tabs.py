from freezegun import freeze_time
from lxml import html

from odoo.tests import HttpCase, tagged
from odoo.tests.common import new_test_user


@tagged("post_install", "-at_install")
@freeze_time("2026-11-01 00:00:00")
class TestAccountTabs(HttpCase):
    def setUp(self):
        super().setUp()
        self.site = self.env['website'].search([('name', '=', 'Q Club')], limit=1)
        config = self.env['qclub.config']._get_for_website(self.site)
        config.write({'online_booking': True, 'online_board': True})
        self.customer = new_test_user(self.env, login='tabs-customer', password='tabs-test',
                                      groups='base.group_portal', name='Tabs Customer')
        other = new_test_user(self.env, login='tabs-other', groups='base.group_portal')
        self.env['qclub.opening.hours']._load_default_hours(self.site)
        kind = self.env['qclub.table.type'].create({'name': 'Tabs type', 'website_id': self.site.id})
        self.table = self.env['qclub.table'].create({
            'name': 'Tabs table', 'website_id': self.site.id, 'type_id': kind.id, 'hourly_price': 20,
        })
        self.own = self.booking(self.customer, '2026-11-06 12:30:00')
        foreign = self.booking(other, '2026-11-07 12:30:00')
        post = self.env['qclub.board.post'].create({
            'booking_id': foreign.id, 'message': 'Other post', 'players_needed': 2,
        })
        self.env['qclub.board.application'].create({
            'post_id': post.id, 'partner_id': self.customer.partner_id.id,
        })
        self.env['qclub.board.reply'].create({
            'post_id': post.id, 'partner_id': other.partner_id.id, 'message': 'Reply',
        })
        self.env['website'].search([('domain', '=', self.base_url())]).write({'domain': False})
        self.site.domain = self.base_url()
        self.env.flush_all()
        self.env.registry.clear_cache()

    def booking(self, user, start):
        booking = self.env['qclub.booking'].create({
            'table_id': self.table.id, 'partner_id': user.partner_id.id,
            'start': start, 'duration_hours': 1,
        })
        booking.action_confirm()
        return booking

    def test_brd_031_tabs_counts_and_status_colours(self):
        self.env['qclub.board.post'].create({
            'booking_id': self.own.id, 'message': 'Own post', 'players_needed': 2,
        })
        cancelled = self.booking(self.customer, '2026-11-08 12:30:00')
        cancelled.action_cancel()
        self.authenticate('tabs-customer', 'tabs-test')
        self.env.flush_all()
        response = self.url_open('/my/billiard')
        self.assertEqual(response.status_code, 200)
        doc = html.fromstring(response.content)
        labels = ['My bookings', 'My posts', 'My join requests', 'Messages']
        ids = ['qclub_my_bookings', 'qclub_my_posts', 'qclub_my_applications', 'qclub_my_messages']
        tabs = doc.xpath("//button[@role='tab']")
        self.assertEqual(len(tabs), 4)
        self.assertEqual([int(tab.xpath('./span')[0].text) for tab in tabs], [2, 1, 1, 1])
        for index, (tab, label, pane_id) in enumerate(zip(tabs, labels, ids)):
            pane = doc.get_element_by_id(pane_id)
            self.assertEqual(pane.get('role'), 'tabpanel')
            self.assertEqual(tab.get('aria-controls'), pane_id)
            self.assertEqual(tab.get('aria-selected'), str(index == 0).lower())
            self.assertEqual(label, tab.text.strip())
            self.assertEqual(int(tab.xpath('./span')[0].text), len(pane.xpath('./article')))
            self.assertEqual('active' in pane.get('class').split(), index == 0)
            self.assertEqual('show' in pane.get('class').split(), index == 0)
        for pane_id, label, colour in [
            ('qclub_my_bookings', 'Confirmed', 'success'),
            ('qclub_my_bookings', 'Cancelled', 'secondary'),
            ('qclub_my_applications', 'Waiting', 'warning'),
            ('qclub_my_posts', 'Open', 'success'),
        ]:
            pills = doc.xpath(
                f"//section[@id='{pane_id}']/article//span"
                f"[contains(@class, 'text-bg-{colour}') and contains(@class, 'rounded-pill')]"
            )
            self.assertIn(label, [pill.text_content() for pill in pills])
