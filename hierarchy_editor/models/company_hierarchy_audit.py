import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError


_logger = logging.getLogger(__name__)


def get_scenario_selection(self):
    return [
        ('parent_to_branch', _('Parent -> Branch')),
        ('branch_to_parent', _('Branch -> Parent')),
        ('branch_to_other_branch', _("Branch -> Another Parent's Branch")),
        ('branch_to_adoptive_parent', _('Branch -> Adoptive Parent of Another Tree')),
        ('subbranch_to_toplevel', _('Sub-branch -> Top-level')),
        ('sibling_swap', _('Sibling Swap')),
    ]


class CompanyHierarchyAudit(models.Model):
    _name = 'company.hierarchy.audit'
    _description = 'Company Hierarchy Audit Log'
    _inherit = ['mail.thread']
    _order = 'date desc'

    name = fields.Char(compute='_compute_name', store=True, readonly=True)
    user_id = fields.Many2one(
        'res.users',
        string='User',
        default=lambda self: self.env.user,
        readonly=True,
        required=True,
    )
    date = fields.Datetime(
        default=fields.Datetime.now,
        readonly=True,
        required=True,
    )
    scenario = fields.Selection(selection=get_scenario_selection, required=True, readonly=True)
    source_company_id = fields.Many2one('res.company', required=True, readonly=True)
    old_parent_id = fields.Many2one('res.company', readonly=True)
    new_parent_id = fields.Many2one('res.company', readonly=True)
    old_parent_path = fields.Char(readonly=True)
    new_parent_path = fields.Char(readonly=True)
    affected_user_ids = fields.Many2many(
        'res.users',
        'company_hierarchy_audit_res_users_rel',
        'audit_id',
        'user_id',
        readonly=True,
    )
    affected_account_count = fields.Integer(readonly=True)
    state = fields.Selection(
        [
            ('pending', 'Pending'),
            ('executed', 'Executed'),
            ('rolled_back', 'Rolled Back'),
            ('failed', 'Failed'),
        ],
        default='pending',
        required=True,
        tracking=True,
    )
    notes = fields.Text()
    preflight_report_json = fields.Text(readonly=True)

    @api.depends('date', 'scenario', 'source_company_id')
    def _compute_name(self):
        for audit in self:
            date_label = fields.Date.to_string(fields.Date.to_date(audit.date)) if audit.date else ''
            scenario_label = dict(get_scenario_selection(audit)).get(audit.scenario, audit.scenario or '')
            company_name = audit.source_company_id.display_name or _('Unknown Company')
            audit.name = _("[%s] %s '%s'", date_label, scenario_label, company_name)

    def write(self, vals):
        """Restrict audit updates to wizard-controlled state and notes changes.

        Inputs are the normal ORM ``vals`` dictionary. The method returns the
        result of ``super().write`` and only mutates existing audit rows when
        the wizard context flag explicitly authorizes changing ``state`` and
        ``notes``.
        """
        if not self.env.context.get('hierarchy_audit_bypass'):
            _logger.warning(
                "Blocked direct write on company hierarchy audit rows %s with fields %s",
                self.ids,
                sorted(vals),
            )
            raise UserError(_('Company hierarchy audit logs are immutable.'))

        allowed_fields = {'state', 'notes'}
        forbidden_fields = set(vals) - allowed_fields
        if forbidden_fields:
            raise UserError(
                _('Only state and notes may be updated on hierarchy audit logs. Blocked fields: %s',
                  ', '.join(sorted(forbidden_fields)))
            )
        return super().write(vals)

    def unlink(self):
        """Forbid deleting audit rows.

        The method takes no inputs beyond ``self`` and always raises a
        ``UserError`` so forensic records remain available after creation.
        """
        _logger.warning("Blocked unlink on company hierarchy audit rows %s", self.ids)
        raise UserError(_('Company hierarchy audit logs cannot be deleted.'))
