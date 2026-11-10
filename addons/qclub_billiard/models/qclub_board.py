"""Shared board models and privacy rules."""

import logging

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, ValidationError

_logger = logging.getLogger(__name__)

BOARD_DISPLAY_NAME = "Q Club Player"


def board_display_name(partner, viewer_is_public):
    """Return a display name without exposing contact or account fields."""
    if viewer_is_public:
        return BOARD_DISPLAY_NAME
    name = (partner.name or "").strip()
    if not name or "@" in name or sum(char.isdigit() for char in name) >= 7:
        return BOARD_DISPLAY_NAME
    return name


def board_posted_label(record):
    """Format the creation instant with the booking's customer timezone and format."""
    return record.env["qclub.booking"]._format_booking_time(
        record.create_date, record.create_date).split(" – ")[0]


COMMUNITY_GUIDELINES = """Community Guidelines
Be respectful. No harassment, hate speech or offensive language.
Keep posts about finding players for your booking. No advertising or spam.
Do not share phone numbers, emails or other personal contact details.
Logged-in members can see the name on your account.
Q Club may remove content or restrict access to the board at any time.
Meeting other players is at your own risk. Q Club is not responsible for arrangements between players."""


def check_board_staff(records):
    if not records.env.user.has_group("qclub_billiard.group_billiard_staff"):
        raise AccessError(records.env._("Only billiard staff may moderate board content."))
    records.check_access("read")


def moderate_content(records, hidden):
    check_board_staff(records)
    records.sudo().write({"hidden": hidden, "hidden_by": records.env.uid,
                          "hidden_at": fields.Datetime.now()})
    return True


class BoardPost(models.Model):
    _name = "qclub.board.post"
    _description = "Booking player wanted post"
    _rec_name = "message"

    booking_id = fields.Many2one("qclub.booking", required=True, ondelete="restrict", index=True)
    website_id = fields.Many2one(related="booking_id.website_id", store=True, index=True)
    partner_id = fields.Many2one(related="booking_id.partner_id", store=True, index=True)
    hidden = fields.Boolean(default=False, index=True)
    hidden_by = fields.Many2one("res.users", readonly=True)
    hidden_at = fields.Datetime(readonly=True)
    message = fields.Text(required=True)
    level = fields.Selection([
        ("any", "Any"), ("beginner", "Beginner"),
        ("intermediate", "Intermediate"), ("advanced", "Advanced"),
    ], required=True, default="any")
    players_needed = fields.Integer(required=True, default=1)
    state = fields.Selection([("open", "Open"), ("closed", "Closed")], required=True, default="open")

    def action_hide(self):
        return moderate_content(self, True)

    def action_restore(self):
        return moderate_content(self, False)

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

    def _customer_message(self):
        """Customer surfaces must never expose moderated original text."""
        self.ensure_one()
        return self.env._("This post was removed.") if self.hidden else self.message

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
            "level": self.level, "remaining": self._remaining(),
        }

    def _remaining(self):
        self.ensure_one()
        return max(0, self.players_needed - self.env["qclub.board.application"].search_count([
            ("post_id", "=", self.id), ("state", "=", "accepted"),
        ]))

    def _update_join_row(self):
        """A real row version serializes capacity decisions under REPEATABLE READ.

        Do not catch SerializationFailure here: Odoo's HTTP transaction retry must
        restart the entire request with a new snapshot.
        """
        self.ensure_one()
        self.flush_recordset()
        self.env.cr.execute("UPDATE qclub_board_post SET write_date = clock_timestamp() WHERE id = %s", [self.id])
        self.invalidate_recordset()
        self.booking_id.invalidate_recordset()
        if not self._is_open():
            raise ValidationError(_("This post is closed."))

    def _queue_email(self, event, recipient, actor):
        self.ensure_one()
        booking = self.booking_id
        config = booking._config()
        if not config.booking_email_from or not recipient.email:
            return
        labels = {
            "new": _("New application"), "accepted": _("Application accepted"),
            "declined": _("Application declined"), "removed": _("Removed from the post"),
            "closed": _("This post is closed."), "changed": _("Booking time or table changed"),
        }
        try:
            with self.env.cr.savepoint():
                domain = (self.website_id.domain or "").rstrip("/")
                if not domain.startswith(("https://", "http://")):
                    return
                body = self.env["ir.qweb"]._render("qclub_billiard.board_email", {
                    "booking": booking, "domain": domain, "event_label": labels[event],
                    "actor_name": board_display_name(actor, False),
                    "time_label": booking._time_label(),
                    "post_url": "%s/billiard/booking?date=%s&post=%s" % (
                        domain, booking.business_date.isoformat(), self.id,
                    ),
                })
                mail = self.env["mail.mail"].sudo().create({
                    "subject": _("Q Club – %s", labels[event]),
                    "email_from": config.booking_email_from, "email_to": recipient.email,
                    "body_html": body, "auto_delete": False,
                })
                # The mail queue cron only runs hourly: send this email as soon as the transaction commits.
                mail.send_after_commit()
        except Exception:
            _logger.exception("Could not queue board email for post %s", self.id)

    def _notify_accepted(self, event):
        for post in self:
            applications = self.env["qclub.board.application"].sudo().search([
                ("post_id", "=", post.id), ("state", "=", "accepted"),
            ])
            for application in applications:
                post._queue_email(event, application.partner_id, post.partner_id)


class BoardTerms(models.Model):
    _name = "qclub.board.terms"
    _description = "Board community guidelines acceptance"

    website_id = fields.Many2one("website", required=True, ondelete="restrict", index=True)
    partner_id = fields.Many2one("res.partner", required=True, ondelete="restrict", index=True)
    accepted_at = fields.Datetime(required=True, default=fields.Datetime.now)

    _website_partner_unique = models.Constraint(
        "UNIQUE(website_id, partner_id)", "Community guidelines have already been accepted.",
    )


class BoardReply(models.Model):
    _name = "qclub.board.reply"
    _description = "Booking board reply"
    _rec_name = "message"
    _order = "id"

    post_id = fields.Many2one("qclub.board.post", required=True, ondelete="restrict", index=True)
    partner_id = fields.Many2one("res.partner", required=True, ondelete="restrict", index=True)
    website_id = fields.Many2one(related="post_id.website_id", store=True, index=True)
    hidden = fields.Boolean(default=False, index=True)
    hidden_by = fields.Many2one("res.users", readonly=True)
    hidden_at = fields.Datetime(readonly=True)
    message = fields.Text(required=True)

    def action_hide(self):
        return moderate_content(self, True)

    def action_restore(self):
        return moderate_content(self, False)

    @api.model_create_multi
    def create(self, vals_list):
        self.check_access("create")
        for values in vals_list:
            post = self.env["qclub.board.post"].browse(values.get("post_id")).exists()
            if not post:
                raise ValidationError(_("This post is unavailable."))
            post._update_join_row()
            if isinstance(values.get("message"), str):
                values["message"] = values["message"].strip()
        return super().create(vals_list)

    @api.constrains("message")
    def _check_message(self):
        for reply in self:
            if not reply.message or not 1 <= len(reply.message.strip()) <= 500:
                raise ValidationError(_("Message must contain 1 to 500 characters."))


class BoardApplication(models.Model):
    _name = "qclub.board.application"
    _description = "Booking board application"
    _order = "id"

    post_id = fields.Many2one("qclub.board.post", required=True, ondelete="restrict", index=True)
    partner_id = fields.Many2one("res.partner", required=True, ondelete="restrict", index=True)
    website_id = fields.Many2one(related="post_id.website_id", store=True, index=True)
    message = fields.Text()
    state = fields.Selection([
        ("pending", "Waiting"), ("accepted", "Accepted"), ("declined", "Declined"),
        ("withdrawn", "Withdrawn"), ("removed", "Removed"),
    ], required=True, default="pending")

    def init(self):
        self.env.cr.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS qclub_board_application_active_unique
            ON qclub_board_application (post_id, partner_id)
            WHERE state IN ('pending', 'accepted', 'declined', 'removed')
        """)

    @api.constrains("message")
    def _check_message(self):
        for application in self:
            if len(application.message or "") > 200:
                raise ValidationError(_("Application message must contain at most 200 characters."))

    @api.model_create_multi
    def create(self, vals_list):
        self.check_access("create")
        for values in vals_list:
            post = self.env["qclub.board.post"].browse(values.get("post_id")).exists()
            if not post:
                raise ValidationError(_("This post is unavailable."))
            post._update_join_row()
            if values.get("partner_id") == post.partner_id.id:
                raise ValidationError(_("You cannot apply to your own post."))
            if not post._remaining():
                raise ValidationError(_("No spots left."))
            if isinstance(values.get("message"), str):
                values["message"] = values["message"].strip()
        applications = super().create(vals_list)
        for application in applications:
            application.post_id._queue_email("new", application.post_id.partner_id, application.partner_id)
        return applications

    def _transition(self, action, actor):
        self.ensure_one()
        self.post_id._update_join_row()
        self.invalidate_recordset()
        if action == "withdraw":
            allowed = actor == self.partner_id and self.state in ("pending", "accepted")
            target = "withdrawn"
        else:
            transitions = {"accept": ("pending", "accepted"), "decline": ("pending", "declined"),
                           "remove": ("accepted", "removed")}
            source, target = transitions.get(action, (None, None))
            allowed = actor == self.post_id.partner_id and self.state == source
        if not allowed:
            raise ValidationError(_("This application cannot be changed."))
        if action == "accept" and not self.post_id._remaining():
            raise ValidationError(_("No spots left."))
        self.write({"state": target})
        if action != "withdraw":
            self.post_id._queue_email(target, self.partner_id, self.post_id.partner_id)


class BoardReport(models.Model):
    _name = "qclub.board.report"
    _description = "Board content report"
    _rec_name = "reason"
    _order = "id desc"

    website_id = fields.Many2one("website", required=True, ondelete="restrict", index=True)
    reporter_id = fields.Many2one("res.partner", required=True, ondelete="restrict", index=True)
    post_id = fields.Many2one("qclub.board.post", ondelete="restrict", index=True)
    reply_id = fields.Many2one("qclub.board.reply", ondelete="restrict", index=True)
    reason = fields.Selection([("spam", "Spam"), ("abuse", "Abuse"),
                               ("personal_information", "Personal information"), ("other", "Other")], required=True)
    note = fields.Text()
    content = fields.Text(compute="_compute_content")
    content_hidden = fields.Boolean(compute="_compute_content")
    state = fields.Selection([("new", "New"), ("resolved", "Resolved")], required=True, default="new")
    resolved_by = fields.Many2one("res.users", readonly=True)
    resolved_at = fields.Datetime(readonly=True)

    _target_xor = models.Constraint(
        "CHECK ((post_id IS NOT NULL) <> (reply_id IS NOT NULL))", "Choose either a post or a reply.",
    )

    def init(self):
        self.env.cr.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS qclub_board_report_post_unique
            ON qclub_board_report (reporter_id, post_id) WHERE post_id IS NOT NULL
        """)
        self.env.cr.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS qclub_board_report_reply_unique
            ON qclub_board_report (reporter_id, reply_id) WHERE reply_id IS NOT NULL
        """)

    @api.depends("post_id.message", "post_id.hidden", "reply_id.message", "reply_id.hidden")
    def _compute_content(self):
        for report in self:
            target = report.post_id or report.reply_id
            report.content = target.message
            report.content_hidden = target.hidden

    @api.constrains("note", "website_id", "post_id", "reply_id")
    def _check_report(self):
        for report in self:
            if len(report.note or "") > 500:
                raise ValidationError(_("Report notes must contain at most 500 characters."))
            target = report.post_id or report.reply_id
            if target and target.website_id != report.website_id:
                raise ValidationError(_("This content is unavailable."))

    def action_hide_and_resolve(self):
        """Hide the reported content and close the report in one step."""
        check_board_staff(self)
        for report in self:
            (report.post_id or report.reply_id).action_hide()
        self._resolve()
        return self._done_notification(_("Content hidden and report resolved."))

    def action_dismiss(self):
        """Close the report without changing the content."""
        check_board_staff(self)
        self._resolve()
        return self._done_notification(_("Report dismissed. The content is still visible."))

    def _done_notification(self, message):
        """Confirm the action on screen and reload the form so its state updates."""
        return {
            "type": "ir.actions.client", "tag": "display_notification",
            "params": {"message": message, "type": "success", "sticky": False,
                       "next": {"type": "ir.actions.act_window_close"}},
        }

    def _resolve(self):
        self.sudo().write({"state": "resolved", "resolved_by": self.env.uid,
                           "resolved_at": fields.Datetime.now()})
        return True


class BoardBan(models.Model):
    _name = "qclub.board.ban"
    _description = "Board customer ban"
    _order = "id desc"

    website_id = fields.Many2one("website", required=True, ondelete="restrict", index=True)
    partner_id = fields.Many2one("res.partner", required=True, ondelete="restrict", index=True)
    reason = fields.Text(required=True)
    until = fields.Datetime()
    active = fields.Boolean(default=True)

    def init(self):
        self.env.cr.execute("""
            CREATE UNIQUE INDEX IF NOT EXISTS qclub_board_ban_active_unique
            ON qclub_board_ban (website_id, partner_id) WHERE active
        """)

    @api.model
    def _is_banned(self, website, partner):
        return bool(self.search_count([
            ("website_id", "=", website.id), ("partner_id", "=", partner.id), ("active", "=", True),
            "|", ("until", "=", False), ("until", ">", fields.Datetime.now()),
        ], limit=1))
