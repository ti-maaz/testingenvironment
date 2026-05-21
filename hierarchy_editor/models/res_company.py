import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


_logger = logging.getLogger(__name__)


class ResCompany(models.Model):
    _inherit = 'res.company'

    hierarchy_change_locked = fields.Boolean(default=True)

    def _get_transaction_blocking_models(self):
        return [
            ('account.move', _('journal entries')),
            ('account.payment', _('payments')),
            ('stock.move', _('stock moves')),
            ('sale.order', _('sales orders')),
            ('purchase.order', _('purchase orders')),
        ]

    def _has_transactional_records(self):
        blocked_models = []
        for model_name, label in self._get_transaction_blocking_models():
            if model_name not in self.env.registry:
                continue
            if self.env[model_name].sudo().search([('company_id', 'in', self.ids)], limit=1):
                blocked_models.append(label)
        return blocked_models

    def unlink(self):
        """Block unsafe company deletion when hierarchy protection or data exists.

        The method takes no explicit inputs. It returns the normal ORM unlink
        result only for unlocked companies that have no detected transactional
        records; otherwise it raises ``UserError`` and leaves all data intact.
        """
        if not self.env.context.get('hierarchy_converter_bypass'):
            locked = self.filtered('hierarchy_change_locked')
            if locked:
                raise UserError(_(
                    "Company hierarchy changes are locked for %(companies)s. "
                    "Use the Company Hierarchy Converter wizard instead of deleting or detaching branch companies.",
                    companies=', '.join(locked.mapped('display_name')),
                ))

        blockers = self._has_transactional_records()
        if blockers:
            raise UserError(_(
                "This company cannot be deleted because it has existing %(records)s. "
                "Use the Company Hierarchy Converter wizard to change parent/branch relationships without touching transactions.",
                records=', '.join(blockers),
            ))
        return super().unlink()

    def write(self, vals):
        """Force hierarchy mutations through the converter wizard.

        ``vals`` is the normal ORM write dictionary. Non-hierarchy writes follow
        Odoo's standard behavior. ``parent_id`` writes are accepted only with
        the wizard bypass context; when bypassed, the method delegates directly
        to the base ORM write for that field so Odoo's native parent-store
        recomputation still runs while the core UI guard is intentionally
        skipped.
        """
        if 'parent_id' not in vals:
            return super().write(vals)

        if not self.env.context.get('hierarchy_converter_bypass'):
            raise UserError(_(
                "The company hierarchy cannot be changed directly. "
                "Use the Company Hierarchy Converter wizard so the change is validated and audited."
            ))

        vals = dict(vals)
        parent_id = vals.pop('parent_id')
        result = True
        if vals:
            result = super().write(vals)

        _logger.info(
            "Writing parent_id=%s on companies %s through hierarchy converter bypass",
            parent_id,
            self.ids,
        )
        parent_result = models.Model.write(self, {'parent_id': parent_id})
        self.env.registry.clear_cache()
        return result and parent_result

    @api.constrains('parent_id')
    def _check_hierarchy_parent_country(self):
        for company in self:
            if company.parent_id and company.country_id != company.parent_id.country_id:
                raise ValidationError(_(
                    "Branches must have the same country as their parent company. "
                    "%(company)s is %(company_country)s, while %(parent)s is %(parent_country)s.",
                    company=company.display_name,
                    company_country=company.country_id.display_name or _('unset'),
                    parent=company.parent_id.display_name,
                    parent_country=company.parent_id.country_id.display_name or _('unset'),
                ))
