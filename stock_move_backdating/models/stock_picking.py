# Copyright 2018 Alex Comba - Agile Business Group
# Copyright 2023 Simone Rubino - TAKOBI
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

from odoo import api, fields, models


class StockPicking(models.Model):
    _inherit = "stock.picking"

    date_backdating = fields.Datetime(
        string="Forced Effective Date",
        help="The Actual Movement Date of the Operations "
        "only if they have all the same value.",
        compute="_compute_date_backdating",
        store=True,
    )

    @api.depends("move_line_ids.date_backdating")
    def _compute_date_backdating(self):
        for picking in self:
            move_lines = picking.move_line_ids
            move_lines_back_dates = move_lines.mapped("date_backdating")
            move_lines_back_date = set(move_lines_back_dates)
            if len(move_lines_back_date) == 1:
                date_backdating = move_lines_back_date.pop()
            else:
                date_backdating = False
            picking.date_backdating = date_backdating

    def _backdating_update_picking_date(self):
        """Update date_done and individual move/quant dates from move line backdating dates.

        In Odoo 19.0 the picking write() override resets all move_ids.date whenever
        date_done is written, so we must re-apply individual move dates after setting
        date_done.  We also fix quant in_date via SQL because that field is readonly
        in the ORM.
        """
        self.ensure_one()
        backdated_lines = self.move_line_ids.filtered("date_backdating")
        if not backdated_lines:
            return True

        # Set date_done to the latest backdating date among all backdated lines.
        # NOTE: picking.write({'date_done': ...}) also resets move_ids.date = date_done
        # (standard Odoo 19.0 write override) — we correct that per-move below.
        max_backdate = max(backdated_lines.mapped("date_backdating"))
        self.date_done = max_backdate

        # Re-apply per-move backdating dates and fix quant in_date.
        for move in self.move_ids.filtered(lambda m: m.state == "done"):
            move_backdate = move.move_line_ids.filtered("date_backdating")[:1].date_backdating
            if not move_backdate:
                continue
            # Writing move.date also syncs move_line_ids.date (Odoo 19.0 write override)
            move.date = move_backdate
            # Fix quant in_date for source and destination locations via SQL
            # (stock.quant.in_date is readonly in the ORM)
            for location in (move.location_id, move.location_dest_id):
                quants = self.env["stock.quant"].sudo().search([
                    ("product_id", "=", move.product_id.id),
                    ("location_id", "=", location.id),
                ])
                quant_ids_to_fix = [q.id for q in quants if q.in_date and q.in_date > move_backdate]
                if quant_ids_to_fix:
                    self._cr.execute(
                        "UPDATE stock_quant SET in_date = %s WHERE id = ANY(%s)",
                        (move_backdate, quant_ids_to_fix),
                    )
            self.env["stock.quant"].invalidate_model(["in_date"])

        return True

    def _backdating_update_stock_valuation_layers_date(self):
        """Set date on linked product.value records same as date on stock.move."""
        self.ensure_one()
        stock_moves = self.move_ids
        stock_moves._backdating_stock_valuation_layers()
        return True

    def _action_done(self):
        # Identify pickings that require backdating BEFORE processing changes state
        pickings_to_backdate = self.filtered(
            lambda p: any(p.move_line_ids.mapped("date_backdating"))
        )
        result = super()._action_done()
        for picking in pickings_to_backdate:
            picking._backdating_update_picking_date()
            picking._backdating_update_stock_valuation_layers_date()
        return result
