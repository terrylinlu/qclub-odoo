from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class QclubConfig(models.Model):
    """Billiard hall settings, one record per website (CFG-001, CFG-002, CFG-004).

    Bookings snapshot these values when they are created (CFG-003, task 1.3),
    so changing a setting only affects new bookings.
    """

    _name = "qclub.config"
    _description = "Billiard Settings"
    _order = "website_id"

    website_id = fields.Many2one("website", string="Website", required=True, ondelete="cascade")
    has_opening_hours = fields.Boolean(compute="_compute_has_opening_hours")

    deposit_ratio = fields.Float(
        string="Deposit (%)", default=50.0, required=True, digits=(5, 2),
        help="Deposit = table fee x this percentage.",
    )
    free_cancel_hours = fields.Integer(
        string="Free Cancellation (hours before start)", default=24, required=True,
        help="Cancelling at least this many hours before the start gives a full deposit refund.",
    )
    no_show_wait_minutes = fields.Integer(
        string="No-show Wait (minutes)", default=30, required=True,
        help="If the customer has not arrived this many minutes after the start, the booking becomes a no-show.",
    )
    lock_minutes = fields.Integer(
        string="Unpaid Hold (minutes)", default=10, required=True,
        help="How long an unpaid booking holds its time slot before it expires.",
    )
    max_consecutive_hours = fields.Integer(string="Max Consecutive Hours", default=4, required=True)
    max_advance_days = fields.Integer(string="Max Days in Advance", default=14, required=True)

    _website_uniq = models.Constraint(
        "UNIQUE(website_id)",
        "Each website can only have one billiard settings record.",
    )
    _deposit_ratio_range = models.Constraint(
        "CHECK(deposit_ratio >= 0 AND deposit_ratio <= 100)",
        "The deposit percentage must be between 0 and 100.",
    )
    _durations_non_negative = models.Constraint(
        "CHECK(free_cancel_hours >= 0 AND no_show_wait_minutes >= 0 AND lock_minutes >= 0 AND max_advance_days >= 0)",
        "Durations cannot be negative.",
    )
    _max_consecutive_min = models.Constraint(
        "CHECK(max_consecutive_hours >= 1)",
        "Max consecutive hours must be at least 1.",
    )

    @api.depends("website_id")
    def _compute_display_name(self):
        for config in self:
            config.display_name = _("Billiard Settings - %s", config.website_id.name or "")

    @api.constrains(
        "deposit_ratio", "free_cancel_hours", "no_show_wait_minutes",
        "lock_minutes", "max_consecutive_hours", "max_advance_days",
    )
    def _check_values(self):
        labels = {
            "free_cancel_hours": _("Free cancellation hours"),
            "no_show_wait_minutes": _("No-show wait minutes"),
            "lock_minutes": _("Unpaid hold minutes"),
            "max_advance_days": _("Max days in advance"),
        }
        for config in self:
            if not 0 <= config.deposit_ratio <= 100:
                raise ValidationError(_("The deposit percentage must be between 0 and 100."))
            for field_name, label in labels.items():
                if config[field_name] < 0:
                    raise ValidationError(_("%s cannot be negative.", label))
            if config.max_consecutive_hours < 1:
                raise ValidationError(_("Max consecutive hours must be at least 1."))

    @api.model
    def _get_for_website(self, website):
        """Return or create default settings using the caller's access rights.

        Trusted server-side callers needing elevated access must explicitly use
        ``sudo()`` at the call site.
        """
        website.ensure_one()
        config = self.search([("website_id", "=", website.id)], limit=1)
        if not config:
            config = self.create({"website_id": website.id})
        return config

    @api.depends("website_id")
    def _compute_has_opening_hours(self):
        for config in self:
            config.has_opening_hours = bool(self.env["qclub.opening.hours"].search_count([
                ("website_id", "=", config.website_id.id),
            ]))

    def action_load_default_opening_hours(self):
        for config in self:
            self.env["qclub.opening.hours"]._load_default_hours(config.website_id)
        self.invalidate_recordset(["has_opening_hours"])
        return {"type": "ir.actions.client", "tag": "reload"}
