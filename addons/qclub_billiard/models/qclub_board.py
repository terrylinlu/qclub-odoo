"""Shared board models and privacy rules."""

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

BOARD_DISPLAY_NAME = "Q Club Player"


def board_display_name(partner, viewer_is_public):
    """Return a display name without exposing contact or account fields."""
    if viewer_is_public:
        return BOARD_DISPLAY_NAME
    name = (partner.name or "").strip()
    if not name or "@" in name or sum(char.isdigit() for char in name) >= 7:
        return BOARD_DISPLAY_NAME
    return name


COMMUNITY_GUIDELINES = """Community Guidelines
Be respectful. No harassment, hate speech or offensive language.
Keep posts about finding players for your booking. No advertising or spam.
Do not share phone numbers, emails or other personal contact details.
Logged-in members can see the name on your account.
Q Club may remove content or restrict access to the board at any time.
Meeting other players is at your own risk. Q Club is not responsible for arrangements between players."""


class BoardPost(models.Model):
    _name = "qclub.board.post"
    _description = "Booking player wanted post"

    booking_id = fields.Many2one("qclub.booking", required=True, ondelete="restrict", index=True)
    website_id = fields.Many2one(related="booking_id.website_id", store=True, index=True)
    partner_id = fields.Many2one(related="booking_id.partner_id", store=True, index=True)
    message = fields.Text(required=True)
    level = fields.Selection([
        ("any", "Any"), ("beginner", "Beginner"),
        ("intermediate", "Intermediate"), ("advanced", "Advanced"),
    ], required=True, default="any")
    players_needed = fields.Integer(required=True, default=1)
    state = fields.Selection([("open", "Open"), ("closed", "Closed")], required=True, default="open")

    _booking_unique = models.Constraint("UNIQUE(booking_id)", "A post already exists for this booking.")

    @api.model_create_multi
    def create(self, vals_list):
        self.check_access("create")
        for values in vals_list:
            booking = self.env["qclub.booking"].browse(values.get("booking_id")).exists()
            if not booking or booking.state != "confirmed" or booking.start <= fields.Datetime.now():
                raise ValidationError(_("Your booking must be confirmed and in the future before you can find players."))
            if isinstance(values.get("message"), str):
                values["message"] = values["message"].strip()
        return super().create(vals_list)

    @api.constrains("message", "players_needed", "booking_id")
    def _check_content(self):
        for post in self:
            config = self.env["qclub.config"]._get_for_website(post.website_id)
            if not post.message or not 1 <= len(post.message.strip()) <= 500:
                raise ValidationError(_("Message must contain 1 to 500 characters."))
            if not 1 <= post.players_needed <= config.board_max_players:
                raise ValidationError(_("Please choose a valid number of players."))

    def _is_open(self):
        self.ensure_one()
        return self.state == "open" and self.booking_id.state == "confirmed" and self.booking_id.start > fields.Datetime.now()

    def _summary(self, viewer_is_public):
        self.ensure_one()
        booking = self.booking_id
        return {
            "id": self.id, "table_id": booking.table_id.id,
            "start": booking.start.isoformat() + "Z", "hours": booking.duration_hours,
            "time_label": booking._time_label(), "table_name": booking.table_id.name,
            "display_name": board_display_name(self.partner_id, viewer_is_public),
            "level": self.level, "remaining": self.players_needed,
        }


class BoardTerms(models.Model):
    _name = "qclub.board.terms"
    _description = "Board community guidelines acceptance"

    website_id = fields.Many2one("website", required=True, ondelete="restrict", index=True)
    partner_id = fields.Many2one("res.partner", required=True, ondelete="restrict", index=True)
    accepted_at = fields.Datetime(required=True, default=fields.Datetime.now)

    _website_partner_unique = models.Constraint(
        "UNIQUE(website_id, partner_id)", "Community guidelines have already been accepted.",
    )
