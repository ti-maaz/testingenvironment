import json
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import HierarchyConverterCommon


@tagged('post_install', '-at_install')
class TestHierarchyConverter(HierarchyConverterCommon):

    def _set_parent(self, company, parent):
        company.with_context(hierarchy_converter_bypass=True).write({'parent_id': parent.id if parent else False})
        self.env.invalidate_all()

    def _run_converter(self, source, scenario, target_parent=None, target_adoptee=None, dry_run=False):
        wizard = self.env['company.hierarchy.converter'].create({
            'source_company_id': source.id,
            'scenario': scenario,
            'target_parent_id': target_parent.id if target_parent else False,
            'target_adoptee_id': target_adoptee.id if target_adoptee else False,
            'dry_run': dry_run,
        })
        wizard.action_preflight()
        findings = json.loads(wizard.preflight_report_json)
        self.assertFalse(findings['blockers'], findings['blockers'])
        wizard.action_execute()
        self.assertTrue(wizard.audit_id)
        return wizard

    def _assert_historical_moves_unchanged(self):
        for move in self.historical_moves:
            self.assertTrue(move.exists())
            self.assertEqual(move.state, 'posted')
            self.assertTrue(move.line_ids)
        self.assertEqual(self.move_a.company_id, self.company_a)
        self.assertEqual(self.move_b.company_id, self.company_b)
        self.assertEqual(self.move_c.company_id, self.company_c)

    def _assert_audit(self, wizard, source, old_parent, new_parent):
        audit = wizard.audit_id
        self.assertEqual(audit.state, 'executed')
        self.assertEqual(audit.source_company_id, source)
        self.assertEqual(audit.old_parent_id, old_parent)
        self.assertEqual(audit.new_parent_id, new_parent)
        self.assertEqual(audit.scenario, wizard.scenario)
        self.assertTrue(audit.preflight_report_json)

    def test_parent_to_branch(self):
        old_parent = self.company_a.parent_id
        wizard = self._run_converter(
            self.company_a,
            'parent_to_branch',
            target_parent=self.company_b,
        )
        self.assertEqual(self.company_a.parent_id, self.company_b)
        self._assert_historical_moves_unchanged()
        self._assert_audit(wizard, self.company_a, old_parent, self.company_b)

    def test_branch_to_parent(self):
        self._set_parent(self.company_a, self.company_b)
        old_parent = self.company_b
        wizard = self._run_converter(self.company_a, 'branch_to_parent')
        self.assertFalse(self.company_a.parent_id)
        self._assert_historical_moves_unchanged()
        self._assert_audit(wizard, self.company_a, old_parent, self.env['res.company'])

    def test_branch_to_other_branch(self):
        self._set_parent(self.company_a, self.company_b)
        old_parent = self.company_b
        wizard = self._run_converter(
            self.company_a,
            'branch_to_other_branch',
            target_parent=self.company_c,
        )
        self.assertEqual(self.company_a.parent_id, self.company_c)
        self._assert_historical_moves_unchanged()
        self._assert_audit(wizard, self.company_a, old_parent, self.company_c)

    def test_branch_to_adoptive_parent(self):
        self._set_parent(self.company_a, self.company_b)
        old_parent = self.company_b
        wizard = self._run_converter(
            self.company_a,
            'branch_to_adoptive_parent',
            target_parent=self.company_c,
            target_adoptee=self.company_c,
        )
        self.assertFalse(self.company_a.parent_id)
        self.assertEqual(self.company_c.parent_id, self.company_a)
        self._assert_historical_moves_unchanged()
        self._assert_audit(wizard, self.company_a, old_parent, self.env['res.company'])

    def test_subbranch_to_toplevel(self):
        self._set_parent(self.company_b, self.company_c)
        self._set_parent(self.company_a, self.company_b)
        old_parent = self.company_b
        wizard = self._run_converter(self.company_a, 'subbranch_to_toplevel')
        self.assertFalse(self.company_a.parent_id)
        self.assertEqual(self.company_b.parent_id, self.company_c)
        self._assert_historical_moves_unchanged()
        self._assert_audit(wizard, self.company_a, old_parent, self.env['res.company'])

    def test_sibling_swap(self):
        self._set_parent(self.company_b, self.company_c)
        self._set_parent(self.company_a, self.company_b)
        old_parent = self.company_b
        wizard = self._run_converter(self.company_a, 'sibling_swap')
        self.assertFalse(self.company_a.parent_id)
        self.assertEqual(self.company_b.parent_id, self.company_a)
        self.assertFalse(self.company_c.parent_id)
        self._assert_historical_moves_unchanged()
        self._assert_audit(wizard, self.company_a, old_parent, self.env['res.company'])

    def test_preflight_country_mismatch(self):
        country = self.env.ref('base.ca')
        target = self.env['res.company'].create({
            'name': 'Co_Country_Mismatch',
            'country_id': country.id,
            'currency_id': country.currency_id.id,
        })
        wizard = self.env['company.hierarchy.converter'].create({
            'source_company_id': self.company_a.id,
            'scenario': 'parent_to_branch',
            'target_parent_id': target.id,
        })
        wizard.action_preflight()
        findings = json.loads(wizard.preflight_report_json)
        self.assertTrue(any('Country mismatch' in blocker for blocker in findings['blockers']))

    def test_preflight_currency_mismatch(self):
        eur = self.setup_other_currency('EUR')
        target = self.env['res.company'].create({
            'name': 'Co_Currency_Mismatch',
            'country_id': self.country.id,
            'currency_id': eur.id,
        })
        wizard = self.env['company.hierarchy.converter'].create({
            'source_company_id': self.company_a.id,
            'scenario': 'parent_to_branch',
            'target_parent_id': target.id,
        })
        wizard.action_preflight()
        findings = json.loads(wizard.preflight_report_json)
        self.assertTrue(any('Currency mismatch' in blocker for blocker in findings['blockers']))

    def test_preflight_circular_reference(self):
        self._set_parent(self.company_b, self.company_a)
        self._set_parent(self.company_c, self.company_b)
        wizard = self.env['company.hierarchy.converter'].create({
            'source_company_id': self.company_a.id,
            'scenario': 'parent_to_branch',
            'target_parent_id': self.company_c.id,
        })
        wizard.action_preflight()
        findings = json.loads(wizard.preflight_report_json)
        self.assertTrue(findings['circular_reference_detected'])
        self.assertTrue(any('descendants' in blocker for blocker in findings['blockers']))

    def test_preflight_missing_required_fields(self):
        wizard = self.env['company.hierarchy.converter'].create({
            'source_company_id': self.company_a.id,
            'scenario': 'parent_to_branch',
        })
        wizard.action_preflight()
        findings = json.loads(wizard.preflight_report_json)
        self.assertTrue(any('target parent' in blocker for blocker in findings['blockers']))

    def test_unlink_blocked_on_company_with_transactions(self):
        with self.assertRaisesRegex(UserError, 'existing'):
            self.company_a.with_context(hierarchy_converter_bypass=True).unlink()

    def test_direct_parent_write_is_blocked(self):
        with self.assertRaisesRegex(UserError, 'wizard'):
            self.company_a.write({'parent_id': self.company_b.id})

    def test_execute_failure_rolls_back_to_savepoint_and_marks_audit_failed(self):
        wizard = self.env['company.hierarchy.converter'].create({
            'source_company_id': self.company_a.id,
            'scenario': 'parent_to_branch',
            'target_parent_id': self.company_b.id,
            'dry_run': False,
        })
        wizard.action_preflight()
        old_parent = self.company_a.parent_id
        with patch.object(type(wizard), '_adjust_account_visibility', side_effect=UserError('Injected rollback failure')):
            with self.assertRaisesRegex(UserError, 'Injected rollback failure'):
                wizard.action_execute()
        self.assertEqual(self.company_a.parent_id, old_parent)
        self.assertEqual(wizard.audit_id.state, 'failed')
