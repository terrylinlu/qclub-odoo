from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


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

    @api.constrains("website_id")
    def _check_table_websites(self):
        Table = self.env["qclub.table"].sudo().with_context(active_test=False)
        for table_type in self:
            if Table.search_count([
                ("type_id", "=", table_type.id),
                ("website_id", "!=", table_type.website_id.id),
            ], limit=1):
                raise ValidationError(_("A table type and all tables using it must belong to the same website."))
