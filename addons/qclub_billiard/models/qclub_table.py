from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class QclubTable(models.Model):
    """A billiard table that customers can book (TBL-001, TBL-003)."""

    _name = "qclub.table"
    _description = "Billiard Table"
    _order = "sequence, name, id"

    name = fields.Char(required=True)
    type_id = fields.Many2one(
        "qclub.table.type",
        string="Table Type",
        required=True,
        ondelete="restrict",
        domain="[('website_id', '=', website_id)]",
    )
    hourly_price = fields.Monetary(string="Hourly Price", required=True, currency_field="currency_id")
    currency_id = fields.Many2one("res.currency", related="website_id.company_id.currency_id", string="Currency")
    active = fields.Boolean(string="Enabled", default=True, help="Disabled tables cannot receive new bookings.")
    sequence = fields.Integer(default=10)
    website_id = fields.Many2one("website", string="Website", required=True, ondelete="cascade", index=True)
    company_id = fields.Many2one(related="website_id.company_id", store=True, index=True)

    _name_website_uniq = models.Constraint(
        "UNIQUE(website_id, name)",
        "A table with this name already exists on this website.",
    )
    _hourly_price_non_negative = models.Constraint(
        "CHECK(hourly_price >= 0)",
        "The hourly price cannot be negative.",
    )

    @api.constrains("hourly_price")
    def _check_hourly_price(self):
        for table in self:
            if table.hourly_price < 0:
                raise ValidationError(_("The hourly price of table %s cannot be negative.", table.name))

    @api.constrains("type_id", "website_id")
    def _check_type_website(self):
        for table in self:
            if table.type_id.website_id != table.website_id:
                raise ValidationError(
                    _("Table %s and its table type must belong to the same website.", table.name)
                )

    def _check_bookable(self):
        """Raise if a table cannot receive new bookings (TBL-003). Called when a booking is created."""
        for table in self.with_context(active_test=False):
            if not table.active:
                raise ValidationError(_("Table %s is disabled and cannot be booked.", table.name))
        return True
