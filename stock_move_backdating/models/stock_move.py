# Copyright 2015-2016 Agile Business Group (<http://www.agilebg.com>)
# Copyright 2016 BREMSKERL-REIBBELAGWERKE EMMERLING GmbH & Co. KG
#    Author Marco Dieckhoff
# Copyright 2018 Alex Comba - Agile Business Group
# Copyright 2023 Simone Rubino - TAKOBI
# License AGPL-3.0 or later (http://www.gnu.org/licenses/agpl.html).

from odoo import fields, models

from .stock_move_line import check_date


class StockMove(models.Model):
    _inherit = "stock.move"

    def _get_price_unit(self):
        """Set date for convert price unit multi currency."""
        self.ensure_one()
        price_unit = super()._get_price_unit()
        date_backdating = self.env.context.get("date_backdating", False)
        if (
            hasattr(self, "purchase_line_id")
            and date_backdating
            and not self.origin_returned_move_id
            and self.purchase_line_id
            and self.product_id.id == self.purchase_line_id.product_id.id
        ):
            self.env["decimal.precision"].precision_get("Product Price")
            line = self.purchase_line_id
            order = line.order_id
            price_unit = line.price_unit
            if order.currency_id != order.company_id.currency_id:
                price_unit = order.currency_id._convert(
                    price_unit,
                    order.company_id.currency_id,
                    order.company_id,
                    date_backdating,
                    round=False,
                )
        return price_unit

    def _backdating_stock_valuation_layers(self):
        """Set date on linked product.value records for each move in `self`."""
        self = self.sudo()
        product_values = self.env["product.value"].search(
            [
                ("move_id", "in", self.ids),
            ],
        )
        for stock_move in self:
            current_move = stock_move
            move_product_values = product_values.filtered(
                lambda pv, move=current_move: pv.move_id == move
            )
            move_product_values.write({"date": stock_move.date})

    def _backdating_action_done(self, moves_todo, cancel_backorder=False):
        """Process the moves, backdating the ones that need to."""
        moves_todo_ids = set(moves_todo.ids)
        move_line = self.mapped("move_line_ids")[:1]
        date_backdating = move_line.date_backdating
        ctx = {}
        if date_backdating:
            # force_period_date is used by _create_account_move() to set the
            # accounting entry date; it expects a Date (not Datetime).
            ctx = {
                "date_backdating": date_backdating,
                "force_period_date": fields.Date.to_date(date_backdating),
            }
            self = self.with_context(**ctx)
        move_todo = super()._action_done(cancel_backorder=cancel_backorder)
        moves_todo_ids.update(move_todo.ids)

        # overwrite date field where applicable
        move_line = self.mapped("move_line_ids")[:1]
        date_backdating = move_line.date_backdating
        if date_backdating:
            check_date(date_backdating)
            self.write({"date": date_backdating})
            self.mapped("move_line_ids").update(
                {
                    "date": date_backdating,
                }
            )
        return self.browse(moves_todo_ids)

    def _action_done(self, cancel_backorder=False):
        moves_todo = self.env["stock.move"]
        has_move_lines_to_backdate = any(self.mapped("move_line_ids.date_backdating"))
        if not has_move_lines_to_backdate:
            res = super()._action_done(cancel_backorder=cancel_backorder)
            if res:
                moves_todo |= res
        else:
            moves_todo = self._backdating_action_done(
                moves_todo, cancel_backorder=cancel_backorder
            )
            moves_todo._backdating_stock_valuation_layers()
        return moves_todo
