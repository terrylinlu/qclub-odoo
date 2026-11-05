from odoo import fields, models


class QclubTableType(models.Model):
    """Configurable table type, e.g. Chinese 8-Ball, Snooker, 9-Ball (TBL-002)."""

    _name = "qclub.table.type"
    _description = "Billiard Table Type"
    _order = "sequence, name, id"

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    website_id = fields.Many2one("website", string="Website", required=True, ondelete="cascade", index=True)

    _name_website_uniq = models.Constraint(
        "UNIQUE(website_id, name)",
        "A table type with this name already exists on this website.",
    )
