import hashlib
import logging
import os

from odoo import api, fields, models


LEGACY_LOR_HTML_SOURCE_SHA256_VALUES = {
    '7933ab3e9507292e811cc7e6d67628ad5245a0146342ae2cdab632854e196b2b',
    '7fc99ff84931b249bf4a4fc885ee78f77ca1bb47fea105ad37769bcd2ac78ca4',
}
LEGACY_LOR_CSS_SOURCE_SHA256_VALUES = {
    'd6feff0ed4e5fb5951a465fa4584fae47e024be33d2c11c3559b233652f572ea',
    '92fc641ccc6221bc4c64081969c88b49a9ca1827265c422e469a1e8fc6c243a1',
    'e9158355a08c9a13556005badfcfe9386887ccb65b01659acd3b48500c815a2e',
    '1d90d7c8215c76d92505ef0327d81dd71a5bf1c0fe7f7a1cdecb46e45e978428',
    'd9c3dd68034a69a6a21ae5be4459784f5aca1a8ae709e474b54c89c48f59d537',
    '52aef6f1252e71e7f90783610c9071ad49b2bb7aa0a207e91062bc74767bac18',
    'cc90886a73f99f37cb6c2531822302fdc68e0f55ecb18056cbe4657cfe839a7a',
    '77213df92d4e6cfce450fb8e1c731863780897c91f5dab2f2e4494dc4c0f9281',
    '66745e74a63489f726692deadfa9c0416c1a5f3aba2295a9cbf5e46b5d45a2e4',
    '9040abc412da213b64a4439646440850a8c40e380bbbfb872216dd181f897e31',
}
SIGNATORY_ROLE_SELECTION = [
    ('primary', 'Primary'),
    ('secondary', 'Secondary'),
]


_logger = logging.getLogger(__name__)


def _module_template_path(filename):
    module_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(module_dir, 'templates', filename)


def _read_module_template(filename):
    try:
        with open(_module_template_path(filename), 'r', encoding='utf-8') as file_obj:
            return file_obj.read()
    except OSError:
        _logger.exception("Unable to read LOR template file: %s", filename)
        return ''


def get_default_lor_html_source():
    return _read_module_template('LOR.html')


def get_default_lor_css_source():
    return _read_module_template('LOR.css')


def _hash_template_source(text_value):
    return hashlib.sha256((text_value or '').encode('utf-8')).hexdigest()


class ResCompany(models.Model):
    _inherit = 'res.company'

    business_activity_include_services = fields.Boolean(
        string='Append "services" to business activity',
        compute='_compute_audit_company_compatibility_fields',
        readonly=True,
    )
    share_capital_paid_status = fields.Selection(
        [('paid', 'Paid'), ('unpaid', 'Unpaid')],
        string='Share capital status',
        compute='_compute_audit_company_compatibility_fields',
        readonly=True,
    )
    show_share_capital_conversion_note = fields.Boolean(
        string='Show share capital conversion note',
        compute='_compute_audit_company_compatibility_fields',
        readonly=True,
    )
    share_conversion_currency = fields.Char(
        string='Original currency',
        compute='_compute_audit_company_compatibility_fields',
        readonly=True,
    )
    share_conversion_original_value = fields.Float(
        string='Original value per share',
        compute='_compute_audit_company_compatibility_fields',
        readonly=True,
    )
    share_conversion_exchange_rate = fields.Float(
        string='Exchange rate',
        compute='_compute_audit_company_compatibility_fields',
        readonly=True,
    )
    show_share_capital_transfer_note = fields.Boolean(
        string='Show share transfer note',
        compute='_compute_audit_company_compatibility_fields',
        readonly=True,
    )
    share_transfer_date = fields.Date(
        string='Transfer date',
        compute='_compute_audit_company_compatibility_fields',
        readonly=True,
    )
    share_transfer_from = fields.Char(
        string='Transferred from',
        compute='_compute_audit_company_compatibility_fields',
        readonly=True,
    )
    share_transfer_shares = fields.Integer(
        string='No. of shares transferred',
        compute='_compute_audit_company_compatibility_fields',
        readonly=True,
    )
    share_transfer_percentage = fields.Float(
        string='Transferred shares (%)',
        compute='_compute_audit_company_compatibility_fields',
        readonly=True,
    )
    share_transfer_to = fields.Char(
        string='Transferred to',
        compute='_compute_audit_company_compatibility_fields',
        readonly=True,
    )
    show_shareholder_note = fields.Boolean(
        string='Show shareholder note',
        compute='_compute_audit_company_compatibility_fields',
        readonly=True,
    )
    show_related_parties_note = fields.Boolean(
        string='Show related parties note',
        compute='_compute_audit_company_compatibility_fields',
        readonly=True,
    )
    owner_include_1 = fields.Boolean(string='Owner 1', compute='_compute_audit_company_compatibility_fields', readonly=True)
    owner_include_2 = fields.Boolean(string='Owner 2', compute='_compute_audit_company_compatibility_fields', readonly=True)
    owner_include_3 = fields.Boolean(string='Owner 3', compute='_compute_audit_company_compatibility_fields', readonly=True)
    owner_include_4 = fields.Boolean(string='Owner 4', compute='_compute_audit_company_compatibility_fields', readonly=True)
    owner_include_5 = fields.Boolean(string='Owner 5', compute='_compute_audit_company_compatibility_fields', readonly=True)
    owner_include_6 = fields.Boolean(string='Owner 6', compute='_compute_audit_company_compatibility_fields', readonly=True)
    owner_include_7 = fields.Boolean(string='Owner 7', compute='_compute_audit_company_compatibility_fields', readonly=True)
    owner_include_8 = fields.Boolean(string='Owner 8', compute='_compute_audit_company_compatibility_fields', readonly=True)
    owner_include_9 = fields.Boolean(string='Owner 9', compute='_compute_audit_company_compatibility_fields', readonly=True)
    owner_include_10 = fields.Boolean(string='Owner 10', compute='_compute_audit_company_compatibility_fields', readonly=True)
    director_include_1 = fields.Boolean(string='Director 1', compute='_compute_audit_company_compatibility_fields', readonly=True)
    director_include_2 = fields.Boolean(string='Director 2', compute='_compute_audit_company_compatibility_fields', readonly=True)
    director_include_3 = fields.Boolean(string='Director 3', compute='_compute_audit_company_compatibility_fields', readonly=True)
    director_include_4 = fields.Boolean(string='Director 4', compute='_compute_audit_company_compatibility_fields', readonly=True)
    director_include_5 = fields.Boolean(string='Director 5', compute='_compute_audit_company_compatibility_fields', readonly=True)
    director_include_6 = fields.Boolean(string='Director 6', compute='_compute_audit_company_compatibility_fields', readonly=True)
    director_include_7 = fields.Boolean(string='Director 7', compute='_compute_audit_company_compatibility_fields', readonly=True)
    director_include_8 = fields.Boolean(string='Director 8', compute='_compute_audit_company_compatibility_fields', readonly=True)
    director_include_9 = fields.Boolean(string='Director 9', compute='_compute_audit_company_compatibility_fields', readonly=True)
    director_include_10 = fields.Boolean(string='Director 10', compute='_compute_audit_company_compatibility_fields', readonly=True)
    signature_include_1 = fields.Boolean(string='Signatory 1', compute='_compute_audit_company_compatibility_fields', readonly=True)
    signature_include_2 = fields.Boolean(string='Signatory 2', compute='_compute_audit_company_compatibility_fields', readonly=True)
    signature_include_3 = fields.Boolean(string='Signatory 3', compute='_compute_audit_company_compatibility_fields', readonly=True)
    signature_include_4 = fields.Boolean(string='Signatory 4', compute='_compute_audit_company_compatibility_fields', readonly=True)
    signature_include_5 = fields.Boolean(string='Signatory 5', compute='_compute_audit_company_compatibility_fields', readonly=True)
    signature_include_6 = fields.Boolean(string='Signatory 6', compute='_compute_audit_company_compatibility_fields', readonly=True)
    signature_include_7 = fields.Boolean(string='Signatory 7', compute='_compute_audit_company_compatibility_fields', readonly=True)
    signature_include_8 = fields.Boolean(string='Signatory 8', compute='_compute_audit_company_compatibility_fields', readonly=True)
    signature_include_9 = fields.Boolean(string='Signatory 9', compute='_compute_audit_company_compatibility_fields', readonly=True)
    signature_include_10 = fields.Boolean(string='Signatory 10', compute='_compute_audit_company_compatibility_fields', readonly=True)
    signature_role_1 = fields.Selection(SIGNATORY_ROLE_SELECTION, string='Signatory role 1', compute='_compute_audit_company_compatibility_fields', readonly=True)
    signature_role_2 = fields.Selection(SIGNATORY_ROLE_SELECTION, string='Signatory role 2', compute='_compute_audit_company_compatibility_fields', readonly=True)
    signature_role_3 = fields.Selection(SIGNATORY_ROLE_SELECTION, string='Signatory role 3', compute='_compute_audit_company_compatibility_fields', readonly=True)
    signature_role_4 = fields.Selection(SIGNATORY_ROLE_SELECTION, string='Signatory role 4', compute='_compute_audit_company_compatibility_fields', readonly=True)
    signature_role_5 = fields.Selection(SIGNATORY_ROLE_SELECTION, string='Signatory role 5', compute='_compute_audit_company_compatibility_fields', readonly=True)
    signature_role_6 = fields.Selection(SIGNATORY_ROLE_SELECTION, string='Signatory role 6', compute='_compute_audit_company_compatibility_fields', readonly=True)
    signature_role_7 = fields.Selection(SIGNATORY_ROLE_SELECTION, string='Signatory role 7', compute='_compute_audit_company_compatibility_fields', readonly=True)
    signature_role_8 = fields.Selection(SIGNATORY_ROLE_SELECTION, string='Signatory role 8', compute='_compute_audit_company_compatibility_fields', readonly=True)
    signature_role_9 = fields.Selection(SIGNATORY_ROLE_SELECTION, string='Signatory role 9', compute='_compute_audit_company_compatibility_fields', readonly=True)
    signature_role_10 = fields.Selection(SIGNATORY_ROLE_SELECTION, string='Signatory role 10', compute='_compute_audit_company_compatibility_fields', readonly=True)

    lor_template_html_source = fields.Text(
        string='LOR HTML Source',
        help='Reference copy only. LOR DOCX generation uses the live module LOR.html file.',
    )
    lor_template_css_source = fields.Text(
        string='LOR CSS Source',
        default=lambda self: self._default_lor_template_css_source(),
        help='CSS-like styling source used while building the LOR DOCX for this company.',
    )

    def _compute_audit_company_compatibility_fields(self):
        for company in self:
            company.business_activity_include_services = True
            company.share_capital_paid_status = company.company_share or 'paid'
            company.show_share_capital_conversion_note = False
            company.share_conversion_currency = 'GBP'
            company.share_conversion_original_value = 100.0
            company.share_conversion_exchange_rate = 4.66
            company.show_share_capital_transfer_note = False
            company.share_transfer_date = False
            company.share_transfer_from = False
            company.share_transfer_shares = 0
            company.share_transfer_percentage = 0.0
            company.share_transfer_to = False
            company.show_shareholder_note = True
            company.show_related_parties_note = False
            for index in range(1, 11):
                company[f'owner_include_{index}'] = True
                company[f'director_include_{index}'] = index == 1
                company[f'signature_include_{index}'] = False
                company[f'signature_role_{index}'] = 'primary' if index == 1 else 'secondary'

    @api.model
    def _default_lor_template_html_source(self):
        return get_default_lor_html_source()

    @api.model
    def _default_lor_template_css_source(self):
        return get_default_lor_css_source()

    @api.model
    def _uses_module_default_lor_template_html(self, html_source):
        if not html_source:
            return True
        source_text = str(html_source or '')
        if source_text == get_default_lor_html_source():
            return True
        return _hash_template_source(source_text) in LEGACY_LOR_HTML_SOURCE_SHA256_VALUES

    def _get_lor_template_html_source(self):
        self.ensure_one()
        if self._uses_module_default_lor_template_html(self.lor_template_html_source):
            return get_default_lor_html_source()
        return self.lor_template_html_source

    def _get_lor_template_css_source(self):
        self.ensure_one()
        return self.lor_template_css_source or self._default_lor_template_css_source()

    @api.model
    def _sync_lor_template_defaults_to_latest_source(self):
        companies = self.with_context(active_test=False).search([])
        default_css = get_default_lor_css_source()

        for company in companies:
            vals = {}
            html_source = company.lor_template_html_source or ''
            css_source = company.lor_template_css_source or ''
            if (
                company._uses_module_default_lor_template_html(html_source)
            ):
                vals['lor_template_html_source'] = False
            if (
                not css_source
                or _hash_template_source(css_source) in LEGACY_LOR_CSS_SOURCE_SHA256_VALUES
            ):
                vals['lor_template_css_source'] = default_css
            if vals:
                company.write(vals)
        return True

    def action_reset_lor_template_defaults(self):
        self.ensure_one()
        self.write({
            'lor_template_html_source': False,
            'lor_template_css_source': self._default_lor_template_css_source(),
        })
        return {'type': 'ir.actions.client', 'tag': 'reload'}
