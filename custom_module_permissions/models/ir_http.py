from odoo import SUPERUSER_ID, models
from odoo.http import request


class IrHttp(models.AbstractModel):
    _inherit = 'ir.http'

    @classmethod
    def _handle_debug(cls):
        super()._handle_debug()

        if not request or not request.session:
            return

        session_uid = request.session.uid
        if not session_uid:
            return

        if session_uid == SUPERUSER_ID:
            return

        user = request.env['res.users'].sudo().browse(session_uid)
        if user.allow_debug_mode:
            return

        if request.httprequest.args.get('debug') is not None or request.session.debug:
            request.session.debug = ''