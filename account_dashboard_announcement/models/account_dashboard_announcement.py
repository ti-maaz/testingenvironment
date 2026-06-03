from odoo import api, fields, models


class AccountDashboardAnnouncement(models.Model):
    _name = "account.dashboard.announcement"
    _description = "Accounting Dashboard Announcement"
    _order = "sequence asc, id desc"

    name = fields.Char(required=True)
    message = fields.Text(required=True)
    active = fields.Boolean(default=True)
    date_start = fields.Date()
    date_end = fields.Date()
    style_type = fields.Selection(
        selection=[
            ("info", "Info"),
            ("warning", "Warning"),
            ("success", "Success"),
            ("danger", "Danger"),
        ],
        required=True,
        default="info",
    )
    sequence = fields.Integer(default=10)
    dismissible = fields.Boolean(default=True)

    @api.model
    def get_active_announcement(self):
        """Return the first active global dashboard announcement for internal users."""
        if not self.env.user.has_group("base.group_user"):
            return False

        today = fields.Date.context_today(self)
        domain = [
            ("active", "=", True),
            "|", ("date_start", "=", False), ("date_start", "<=", today),
            "|", ("date_end", "=", False), ("date_end", ">=", today),
        ]
        announcement = self.sudo().search(
            domain,
            order="sequence asc, id desc",
            limit=1,
        )
        if not announcement:
            return False

        return {
            "id": announcement.id,
            "name": announcement.name,
            "message": announcement.message,
            "style_type": announcement.style_type,
            "dismissible": announcement.dismissible,
        }
