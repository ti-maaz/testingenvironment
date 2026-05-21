import json
import logging
import traceback

from odoo import _, Command, fields, models
from odoo.exceptions import UserError
from odoo.tools import html_escape

from ..models.company_hierarchy_audit import get_scenario_selection


_logger = logging.getLogger(__name__)


SCENARIO_ALIASES = {
    'Parent -> Branch': 'parent_to_branch',
    'Parent → Branch': 'parent_to_branch',
    'Branch -> Parent': 'branch_to_parent',
    'Branch → Parent': 'branch_to_parent',
    "Branch -> Another Parent's Branch": 'branch_to_other_branch',
    "Branch → Another Parent's Branch": 'branch_to_other_branch',
    'Branch -> Adoptive Parent of Another Tree': 'branch_to_adoptive_parent',
    'Branch → Adoptive Parent of Another Tree': 'branch_to_adoptive_parent',
    'Sub-branch -> Top-level': 'subbranch_to_toplevel',
    'Sub-branch → Top-level': 'subbranch_to_toplevel',
    'Sibling Swap': 'sibling_swap',
}

SCENARIO_KEYS = {
    'parent_to_branch',
    'branch_to_parent',
    'branch_to_other_branch',
    'branch_to_adoptive_parent',
    'subbranch_to_toplevel',
    'sibling_swap',
}


class CompanyHierarchyConverter(models.TransientModel):
    _name = 'company.hierarchy.converter'
    _description = 'Company Hierarchy Converter'

    source_company_id = fields.Many2one('res.company', required=True)
    scenario = fields.Selection(selection=get_scenario_selection, required=True)
    target_parent_id = fields.Many2one('res.company')
    target_adoptee_id = fields.Many2one('res.company')
    dry_run = fields.Boolean(default=True)
    adjust_account_visibility = fields.Boolean(
        string='Adjust Old COA Visibility',
        default=False,
        help='Link non-restricted historical accounts to the new hierarchy root. Leave disabled for the safest conversion.',
    )
    state = fields.Selection(
        [
            ('draft', 'Draft'),
            ('preflight_done', 'Preflight Done'),
            ('executed', 'Executed'),
            ('failed', 'Failed'),
        ],
        default='draft',
        required=True,
    )
    preflight_report = fields.Html(readonly=True)
    preflight_report_json = fields.Text(readonly=True)
    affected_user_count = fields.Integer(readonly=True)
    affected_account_count = fields.Integer(readonly=True)
    circular_reference_detected = fields.Boolean(readonly=True)
    audit_id = fields.Many2one('company.hierarchy.audit', readonly=True)

    def action_preflight(self):
        """Validate the requested hierarchy conversion and keep the wizard open.

        The method reads the wizard fields, writes the generated HTML and JSON
        reports back to this transient record, and returns an ``act_window``
        dictionary pointing to the same wizard dialog.
        """
        self.ensure_one()
        with self.env.cr.savepoint():
            findings = self._run_preflight()
            self._write_preflight_result(findings)
        return self._reload_action()

    def action_execute(self):
        """Execute a preflighted hierarchy conversion.

        The method re-runs preflight, creates an audit row, optionally performs
        the hierarchy mutation and related visibility updates inside a
        savepoint, then returns a notification action. It raises ``UserError``
        when blockers are found or the wizard is not in the correct state.
        """
        self.ensure_one()
        if self.state != 'preflight_done':
            raise UserError(_('Run preflight before executing a hierarchy conversion.'))

        findings = self._run_preflight()
        if findings['blockers']:
            raise UserError(_('Preflight blockers must be resolved before execution:\n%s', '\n'.join(findings['blockers'])))

        report_json = self._json_dump(findings)
        audit = self._create_audit(findings, report_json)

        if self.dry_run:
            with self.env.cr.savepoint():
                self.write({
                    'state': 'executed',
                    'audit_id': audit.id,
                    'preflight_report': self._build_html_report(findings),
                    'preflight_report_json': report_json,
                    'affected_user_count': len(findings['affected_user_ids']),
                    'affected_account_count': findings['affected_account_count'],
                    'circular_reference_detected': findings['circular_reference_detected'],
                })
            return self._notification(
                _('Dry run complete. No company hierarchy records were changed.'),
                notification_type='success',
            )

        try:
            with self.env.cr.savepoint():
                accounts_to_link = self._get_precomputed_account_visibility_accounts()
                affected_users = self.env['res.users'].sudo().browse(findings['affected_user_ids'])
                converter = self.with_context(hierarchy_converter_bypass=True)
                method = getattr(converter, self._get_scenario_method_name())
                method()
                affected_users = converter._refresh_user_access(affected_users)
                affected_account_count = converter._adjust_account_visibility(accounts_to_link)
                audit.with_context(hierarchy_audit_bypass=True).write({
                    'state': 'executed',
                    'notes': _('Execution completed. Affected users: %(users)s. Affected accounts: %(accounts)s.',
                               users=len(affected_users),
                               accounts=affected_account_count),
                })
                self.write({
                    'state': 'executed',
                    'audit_id': audit.id,
                    'affected_user_count': len(affected_users),
                    'affected_account_count': affected_account_count,
                })
        except Exception:
            failure_notes = traceback.format_exc()
            _logger.exception(
                "Company hierarchy conversion failed. wizard=%s scenario=%s source_company=%s",
                self.id,
                self.scenario,
                self.source_company_id.id,
            )
            audit.with_context(hierarchy_audit_bypass=True).write({
                'state': 'failed',
                'notes': failure_notes,
            })
            self.write({'state': 'failed', 'audit_id': audit.id})
            raise

        return self._notification(_('Company hierarchy conversion executed.'), notification_type='success')

    def action_open_audit(self):
        """Open the audit row created by this wizard.

        The method returns an ``act_window`` dictionary for the linked audit
        record and raises ``UserError`` when no audit row has been created yet.
        """
        self.ensure_one()
        if not self.audit_id:
            raise UserError(_('No hierarchy audit log is linked to this wizard yet.'))
        return {
            'type': 'ir.actions.act_window',
            'name': _('Hierarchy Audit Log'),
            'res_model': 'company.hierarchy.audit',
            'res_id': self.audit_id.id,
            'views': [(False, 'form')],
            'view_mode': 'form',
            'target': 'current',
        }

    def _do_scenario_parent_to_branch(self):
        self.ensure_one()
        source = self.source_company_id
        target_parent = self.target_parent_id
        if source.parent_id:
            raise UserError(_('%s is already a branch. Parent -> Branch only accepts standalone companies.', source.display_name))
        if not target_parent:
            raise UserError(_('Select the target parent company before executing Parent -> Branch.'))
        if self._detect_circular_reference(source, target_parent):
            raise UserError(_('The target parent cannot be the source company or one of its descendants.'))

        _logger.info(
            "Executing Parent -> Branch hierarchy conversion: source_company=%s target_parent=%s",
            source.id,
            target_parent.id,
        )
        self._set_parent(source, target_parent)

    def _do_scenario_branch_to_parent(self):
        self.ensure_one()
        source = self.source_company_id
        if not source.parent_id:
            raise UserError(_('%s is already a standalone company.', source.display_name))

        _logger.info(
            "Executing Branch -> Parent hierarchy conversion: source_company=%s old_parent=%s",
            source.id,
            source.parent_id.id,
        )
        self._set_parent(source, self.env['res.company'])

    def _do_scenario_branch_to_other_branch(self):
        self.ensure_one()
        source = self.source_company_id
        target_parent = self.target_parent_id
        if not source.parent_id:
            raise UserError(_('%s is not currently a branch.', source.display_name))
        if not target_parent:
            raise UserError(_('Select the target parent company before executing this scenario.'))
        if source.parent_id == target_parent:
            raise UserError(_('%s is already under the selected target parent.', source.display_name))
        if self._detect_circular_reference(source, target_parent):
            raise UserError(_('The target parent cannot be the source company or one of its descendants.'))

        _logger.info(
            "Executing Branch -> Another Parent's Branch conversion: source_company=%s old_parent=%s target_parent=%s",
            source.id,
            source.parent_id.id,
            target_parent.id,
        )
        self._set_parent(source, target_parent)

    def _do_scenario_branch_to_adoptive_parent(self):
        self.ensure_one()
        source = self.source_company_id
        target_adoptee = self.target_adoptee_id
        if not source.parent_id:
            raise UserError(_('%s must start as a branch for this scenario.', source.display_name))
        if not target_adoptee:
            raise UserError(_('Select the standalone company to adopt before executing this scenario.'))
        if target_adoptee.parent_id:
            raise UserError(_('%s must be standalone before it can be adopted.', target_adoptee.display_name))
        if self._detect_circular_reference(target_adoptee, source):
            raise UserError(_('The source company cannot be a descendant of the company it will adopt.'))

        _logger.info(
            "Executing Branch -> Adoptive Parent conversion: source_company=%s old_parent=%s target_adoptee=%s",
            source.id,
            source.parent_id.id,
            target_adoptee.id,
        )
        self._set_parent(source, self.env['res.company'])
        self._set_parent(target_adoptee, source)

    def _do_scenario_subbranch_to_toplevel(self):
        self.ensure_one()
        source = self.source_company_id
        if not source.parent_id or not source.parent_id.parent_id:
            raise UserError(_('%s must be a sub-branch with both a parent and grandparent.', source.display_name))

        _logger.info(
            "Executing Sub-branch -> Top-level conversion: source_company=%s old_parent=%s old_grandparent=%s",
            source.id,
            source.parent_id.id,
            source.parent_id.parent_id.id,
        )
        self._set_parent(source, self.env['res.company'])

    def _do_scenario_sibling_swap(self):
        self.ensure_one()
        source = self.source_company_id
        old_parent = source.parent_id
        if not old_parent:
            raise UserError(_('%s must be a branch to swap with its parent.', source.display_name))

        _logger.info(
            "Executing Sibling Swap conversion: source_company=%s old_parent=%s old_grandparent=%s",
            source.id,
            old_parent.id,
            old_parent.parent_id.id if old_parent.parent_id else False,
        )
        self._set_parent(source, self.env['res.company'])
        self._set_parent(old_parent, self.env['res.company'])
        self._set_parent(old_parent, source)

    def _run_preflight(self):
        self.ensure_one()
        blockers = []
        warnings = []
        infos = []
        source = self.source_company_id
        scenario = self._normalized_scenario()
        expected_new_parent = self._get_expected_new_parent()
        circular_reference_detected = False

        blockers.extend(self._validate_required_fields())
        blockers.extend(self._validate_scenario_shape())
        blockers.extend(self._validate_country_currency_for_scenario())
        blockers.extend(self._validate_lock_dates_for_scenario())

        for origin, target in self._get_circular_reference_pairs():
            if self._detect_circular_reference(origin, target):
                circular_reference_detected = True
                blockers.append(_('The target parent cannot be the source company or one of its descendants.'))

        affected_user_ids = self._get_preflight_affected_users().ids
        affected_account_count = len(self._get_precomputed_account_visibility_accounts())

        infos.append(_('Source company: %s', source.display_name if source else _('not selected')))
        if expected_new_parent:
            infos.append(_('Expected new parent: %s', expected_new_parent.display_name))
        else:
            infos.append(_('Expected new parent: standalone top-level company'))
        if scenario == 'branch_to_adoptive_parent' and self.target_adoptee_id:
            infos.append(_('Company to adopt after promotion: %s', self.target_adoptee_id.display_name))
        if not self.adjust_account_visibility:
            warnings.append(_(
                'Old chart-of-accounts visibility adjustment is disabled. Existing accounts will not be linked to the new hierarchy root.'
            ))

        return {
            'scenario': scenario,
            'raw_scenario': self.scenario,
            'scenario_label': dict(get_scenario_selection(self)).get(scenario, self.scenario),
            'source_company_id': source.id if source else False,
            'source_company_name': source.display_name if source else False,
            'old_parent_id': source.parent_id.id if source and source.parent_id else False,
            'old_parent_name': source.parent_id.display_name if source and source.parent_id else False,
            'new_parent_id': expected_new_parent.id if expected_new_parent else False,
            'new_parent_name': expected_new_parent.display_name if expected_new_parent else False,
            'old_parent_path': source.parent_path if source else False,
            'new_parent_path': self._predict_parent_path(source, expected_new_parent) if source else False,
            'target_parent_id': self.target_parent_id.id if self.target_parent_id else False,
            'target_adoptee_id': self.target_adoptee_id.id if self.target_adoptee_id else False,
            'affected_user_ids': affected_user_ids,
            'affected_account_count': affected_account_count,
            'circular_reference_detected': circular_reference_detected,
            'blockers': blockers,
            'warnings': warnings,
            'infos': infos,
            'dry_run': self.dry_run,
            'adjust_account_visibility': self.adjust_account_visibility,
        }

    def _validate_required_fields(self):
        blockers = []
        scenario = self._normalized_scenario()
        if not self.source_company_id:
            blockers.append(_('Select a source company.'))
        if not scenario:
            blockers.append(_('Select a conversion scenario.'))
        if scenario in {'parent_to_branch', 'branch_to_other_branch', 'branch_to_adoptive_parent'} and not self.target_parent_id:
            blockers.append(_('Select a target parent company for this scenario.'))
        if scenario == 'branch_to_adoptive_parent' and not self.target_adoptee_id:
            blockers.append(_('Select the standalone company to adopt for this scenario.'))
        return blockers

    def _validate_scenario_shape(self):
        source = self.source_company_id
        target_parent = self.target_parent_id
        target_adoptee = self.target_adoptee_id
        scenario = self._normalized_scenario()
        blockers = []
        if not source or not scenario:
            return blockers

        if target_parent and source == target_parent:
            blockers.append(_('The source company and target parent must be different companies.'))
        if target_adoptee and source == target_adoptee:
            blockers.append(_('The source company and target adoptee must be different companies.'))

        if scenario == 'parent_to_branch':
            if source.parent_id:
                blockers.append(_('%s is already a branch. Choose a standalone source company.', source.display_name))
        elif scenario == 'branch_to_parent':
            if not source.parent_id:
                blockers.append(_('%s is already a standalone company.', source.display_name))
        elif scenario == 'branch_to_other_branch':
            if not source.parent_id:
                blockers.append(_('%s is not currently a branch.', source.display_name))
            if target_parent and source.parent_id == target_parent:
                blockers.append(_('%s is already under the selected target parent.', source.display_name))
        elif scenario == 'branch_to_adoptive_parent':
            if not source.parent_id:
                blockers.append(_('%s must start as a branch for this scenario.', source.display_name))
            if target_adoptee and target_adoptee.parent_id:
                blockers.append(_('%s must be a standalone company before it can be adopted.', target_adoptee.display_name))
            if target_parent and target_adoptee and target_parent != target_adoptee:
                blockers.append(_('For the adoptive-parent scenario, target parent and target adoptee must be the same standalone company.'))
        elif scenario == 'subbranch_to_toplevel':
            if not source.parent_id or not source.parent_id.parent_id:
                blockers.append(_('%s must be a sub-branch with both a parent and grandparent.', source.display_name))
        elif scenario == 'sibling_swap':
            if not source.parent_id:
                blockers.append(_('%s must be a branch to swap with its parent.', source.display_name))
        else:
            blockers.append(_('Select a supported conversion scenario. Current value: %s', self.scenario or _('empty')))

        return blockers

    def _validate_country_currency_for_scenario(self):
        blockers = []
        for source, target in self._get_country_currency_pairs():
            blockers.extend(self._validate_country_currency(source, target))
        return blockers

    def _validate_country_currency(self, source, target):
        blockers = []
        if not source or not target:
            return blockers
        if source.country_id != target.country_id:
            blockers.append(_(
                "Country mismatch: %(source)s uses %(source_country)s, while %(target)s uses %(target_country)s.",
                source=source.display_name,
                source_country=source.country_id.display_name or _('unset'),
                target=target.display_name,
                target_country=target.country_id.display_name or _('unset'),
            ))
        if source.currency_id != target.currency_id:
            blockers.append(_(
                "Currency mismatch: %(source)s uses %(source_currency)s, while %(target)s uses %(target_currency)s.",
                source=source.display_name,
                source_currency=source.currency_id.display_name or _('unset'),
                target=target.display_name,
                target_currency=target.currency_id.display_name or _('unset'),
            ))
        return blockers

    def _validate_lock_dates_for_scenario(self):
        blockers = []
        source = self.source_company_id
        scenario = self._normalized_scenario()
        if not source or not scenario:
            return blockers

        pairs = []
        if scenario in {'parent_to_branch', 'branch_to_other_branch'} and self.target_parent_id:
            pairs.append((source.root_id, self.target_parent_id.root_id))
        elif scenario in {'branch_to_parent', 'subbranch_to_toplevel', 'sibling_swap'} and source.root_id != source:
            pairs.append((source.root_id, source))
        elif scenario == 'branch_to_adoptive_parent':
            if source.root_id != source:
                pairs.append((source.root_id, source))
            if self.target_adoptee_id:
                pairs.append((self.target_adoptee_id.root_id, source))

        checked = set()
        for left, right in pairs:
            key = (left.id, right.id)
            if left and right and left != right and key not in checked:
                checked.add(key)
                blockers.extend(self._validate_lock_dates(left, right))
        return blockers

    def _validate_lock_dates(self, source, target):
        blockers = []
        for field_name in self._get_lock_date_field_names():
            source_date = source[field_name]
            target_date = target[field_name]
            if source_date != target_date:
                field_label = self.env['res.company']._fields[field_name].string
                blockers.append(_(
                    "Lock-date mismatch on %(field)s: %(source)s has %(source_date)s, while %(target)s has %(target_date)s.",
                    field=field_label,
                    source=source.display_name,
                    source_date=source_date or _('unset'),
                    target=target.display_name,
                    target_date=target_date or _('unset'),
                ))
        return blockers

    def _detect_circular_reference(self, source, target_parent):
        if not source or not target_parent:
            return False
        if source == target_parent:
            return True
        return bool(self.env['res.company'].sudo().search([
            ('id', 'child_of', source.id),
            ('id', '=', target_parent.id),
        ], limit=1))

    def _adjust_account_visibility(self, accounts):
        accounts = accounts.sudo()
        if not accounts:
            return 0
        link_company = self._get_expected_new_tree_root()
        if not link_company:
            return 0
        target_root = link_company.root_id
        generated_codes = set()
        _logger.info(
            "Linking %s account.account records to hierarchy root company %s",
            len(accounts),
            link_company.id,
        )
        for account in accounts:
            vals = {'company_ids': [Command.link(link_company.id)]}
            if not account.with_company(target_root).code:
                base_code = self._get_source_account_code(account)
                new_code = account.with_company(target_root)._search_new_account_code(base_code, generated_codes)
                generated_codes.add(new_code)
                vals['code_mapping_ids'] = [Command.create({
                    'company_id': target_root.id,
                    'code': new_code,
                })]
            account.write(vals)
        return len(accounts)

    def _get_source_account_code(self, account):
        account = account.sudo()
        source_company = (account.company_ids & self.source_company_id.root_id)[:1] or account.company_ids[:1]
        code = False
        if source_company:
            code = account.with_company(source_company.root_id).code or account.with_company(source_company).code
        code = code or account.code or account.placeholder_code or account.id
        return str(code)

    def _refresh_user_access(self, affected_users):
        companies_to_link = self._get_companies_to_keep_accessible().sudo()
        for user in affected_users.sudo():
            commands = [Command.link(company.id) for company in companies_to_link - user.company_ids]
            if user.company_id and user.company_id not in user.company_ids:
                commands.append(Command.link(user.company_id.id))
            if commands:
                user.write({'company_ids': commands})
        return affected_users

    def _build_html_report(self, findings):
        def render_list(items, empty_label):
            if not items:
                return '<p style="margin: 4px 0; color: #667085;">%s</p>' % html_escape(empty_label)
            return '<ul style="margin: 4px 0 0 18px;">%s</ul>' % ''.join(
                '<li>%s</li>' % html_escape(item) for item in items
            )

        status = _('Blocked') if findings['blockers'] else _('Ready')
        status_color = '#b42318' if findings['blockers'] else '#027a48'
        return """
            <div style="font-size: 14px; line-height: 1.45;">
                <h3 style="margin: 0 0 8px 0;">%s</h3>
                <p style="margin: 0 0 10px 0;">
                    <strong>%s</strong>
                    <span style="color: %s; font-weight: 600;">%s</span>
                </p>
                <p style="margin: 0 0 10px 0;"><strong>%s</strong> %s -&gt; %s</p>
                <h4 style="margin: 12px 0 4px 0;">%s</h4>
                %s
                <h4 style="margin: 12px 0 4px 0;">%s</h4>
                %s
                <h4 style="margin: 12px 0 4px 0;">%s</h4>
                %s
                <p style="margin: 12px 0 0 0; color: #475467;">
                    %s: %s | %s: %s
                </p>
            </div>
        """ % (
            html_escape(_('Hierarchy Conversion Preflight')),
            html_escape(_('Status:')),
            status_color,
            html_escape(status),
            html_escape(_('Parent path:')),
            html_escape(findings.get('old_parent_path') or _('empty')),
            html_escape(findings.get('new_parent_path') or _('empty')),
            html_escape(_('Blockers')),
            render_list(findings['blockers'], _('No blockers detected.')),
            html_escape(_('Warnings')),
            render_list(findings['warnings'], _('No warnings.')),
            html_escape(_('Details')),
            render_list(findings['infos'], _('No details.')),
            html_escape(_('Affected users')),
            len(findings['affected_user_ids']),
            html_escape(_('Affected accounts')),
            findings['affected_account_count'],
        )

    def _reload_action(self):
        return {
            'type': 'ir.actions.act_window',
            'name': _('Company Hierarchy Converter'),
            'res_model': self._name,
            'res_id': self.id,
            'views': [(False, 'form')],
            'view_mode': 'form',
            'target': 'new',
        }

    def _notification(self, message, notification_type='info'):
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'type': notification_type,
                'message': message,
                'next': self._reload_action(),
            },
        }

    def _write_preflight_result(self, findings):
        report_json = self._json_dump(findings)
        self.write({
            'state': 'preflight_done',
            'preflight_report': self._build_html_report(findings),
            'preflight_report_json': report_json,
            'affected_user_count': len(findings['affected_user_ids']),
            'affected_account_count': findings['affected_account_count'],
            'circular_reference_detected': findings['circular_reference_detected'],
        })

    def _create_audit(self, findings, report_json):
        return self.env['company.hierarchy.audit'].sudo().create({
            'user_id': self.env.user.id,
            'scenario': self._normalized_scenario(),
            'source_company_id': self.source_company_id.id,
            'old_parent_id': findings['old_parent_id'],
            'new_parent_id': findings['new_parent_id'],
            'old_parent_path': findings['old_parent_path'],
            'new_parent_path': findings['new_parent_path'],
            'affected_user_ids': [Command.set(findings['affected_user_ids'])],
            'affected_account_count': findings['affected_account_count'],
            'state': 'pending',
            'preflight_report_json': report_json,
        })

    def _set_parent(self, company, parent):
        company.with_context(hierarchy_converter_bypass=True).write({'parent_id': parent.id if parent else False})

    def _get_scenario_method_name(self):
        return '_do_scenario_%s' % self._normalized_scenario()

    def _get_expected_new_parent(self):
        if self._normalized_scenario() in {'parent_to_branch', 'branch_to_other_branch'}:
            return self.target_parent_id
        return self.env['res.company']

    def _get_expected_new_tree_root(self):
        expected_parent = self._get_expected_new_parent()
        if expected_parent:
            return expected_parent.root_id
        return self.source_company_id

    def _predict_parent_path(self, source, expected_parent):
        if not source:
            return False
        if not expected_parent:
            return '%s/' % source.id
        parent_path = expected_parent.parent_path or '%s/' % expected_parent.id
        return '%s%s/' % (parent_path, source.id)

    def _get_lock_date_field_names(self):
        company_fields = self.env['res.company']._fields
        return sorted(
            field_name
            for field_name, field in company_fields.items()
            if field.type == 'date'
            and field_name.endswith('_lock_date')
            and not field_name.startswith('user_')
        )

    def _get_country_currency_pairs(self):
        source = self.source_company_id
        scenario = self._normalized_scenario()
        if not source:
            return []
        if scenario in {'parent_to_branch', 'branch_to_other_branch'} and self.target_parent_id:
            return [(source, self.target_parent_id)]
        if scenario == 'branch_to_adoptive_parent' and self.target_adoptee_id:
            return [(source, self.target_adoptee_id)]
        return []

    def _get_circular_reference_pairs(self):
        source = self.source_company_id
        scenario = self._normalized_scenario()
        if not source:
            return []
        if scenario in {'parent_to_branch', 'branch_to_other_branch'} and self.target_parent_id:
            return [(source, self.target_parent_id)]
        if scenario == 'branch_to_adoptive_parent' and self.target_adoptee_id:
            return [(self.target_adoptee_id, source)]
        return []

    def _get_preflight_affected_users(self):
        source = self.source_company_id
        if not source:
            return self.env['res.users']
        companies = self._get_prechange_company_scope()
        return self.env['res.users'].sudo().search([('company_ids', 'in', companies.ids)])

    def _get_prechange_company_scope(self):
        companies = self.env['res.company'].sudo()
        source = self.source_company_id
        if source:
            companies |= source
            companies |= source.root_id
            companies |= self.env['res.company'].sudo().search([('id', 'child_of', source.id)])
        if self.target_parent_id:
            companies |= self.target_parent_id
            companies |= self.target_parent_id.root_id
        if self.target_adoptee_id:
            companies |= self.target_adoptee_id
            companies |= self.target_adoptee_id.root_id
            companies |= self.env['res.company'].sudo().search([('id', 'child_of', self.target_adoptee_id.id)])
        return companies

    def _get_companies_to_keep_accessible(self):
        companies = self.env['res.company'].sudo()
        source = self.source_company_id
        if source:
            companies |= source.root_id
            companies |= self.env['res.company'].sudo().search([('id', 'child_of', source.id)])
        if self._normalized_scenario() == 'branch_to_adoptive_parent' and self.target_adoptee_id:
            companies |= self.env['res.company'].sudo().search([('id', 'child_of', self.target_adoptee_id.id)])
        return companies

    def _get_precomputed_account_visibility_accounts(self):
        source = self.source_company_id
        if not source or not self.adjust_account_visibility:
            return self.env['account.account']
        accounts = self._get_account_visibility_accounts(
            source,
            source.root_id,
            self._get_expected_new_tree_root(),
        )
        if self._normalized_scenario() == 'branch_to_adoptive_parent' and self.target_adoptee_id:
            accounts |= self._get_account_visibility_accounts(
                self.target_adoptee_id,
                self.target_adoptee_id.root_id,
                source,
            )
        return accounts

    def _get_account_visibility_accounts(self, company, old_tree_root, new_tree_root):
        if not company or not old_tree_root or not new_tree_root or old_tree_root == new_tree_root:
            return self.env['account.account']
        accounts = self.env['account.account'].sudo().search([('company_ids', 'parent_of', company.id)])
        return accounts.filtered(
            lambda account: account.account_type not in {'asset_cash', 'equity_unaffected'}
            and new_tree_root not in account.company_ids
        )

    def _normalized_scenario(self):
        scenario = (self.scenario or '').strip()
        scenario = SCENARIO_ALIASES.get(scenario, scenario)
        return scenario if scenario in SCENARIO_KEYS else scenario

    def _json_dump(self, findings):
        return json.dumps(findings, sort_keys=True, default=str)
