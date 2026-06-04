import base64
import copy
import hashlib
import json
import logging
import os
import re
import time
from lxml import etree, html

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


REPORT_TYPE_SELECTION = [
    ('period', 'Financial Statements for the Period Ended'),
    ('year', 'Financial Statements for the Year Ended'),
    ('management', 'Management Accounts for the Period Ended'),
]

AUDIT_PERIOD_CATEGORY_SELECTION = [
    ('cessation_2y', '2 Years Cessation'),
    ('cessation_1y', '1 Year Cessation'),
    ('normal_1y', '1 Year Normal'),
    ('normal_2y', '2 Years Normal'),
    ('dormant_1y', '1 Year Dormant'),
    ('dormant_2y', '2 Years Dormant'),
]

TOC_SECTION_SEQUENCE = [
    ('entity_information', 'Entity information'),
    ('report_of_directors', 'Report of directors'),
    ('independent_auditor_report', 'Independent auditor report'),
    ('balance_sheet_page', 'Statement of financial position'),
    ('profit_loss', 'Statement of profit and loss'),
    ('other_comprehensive_income', 'Statement of other comprehensive income'),
    ('changes_in_equity', 'Statement of changes in equity'),
    ('cash_flows', 'Statement of cash flows'),
    ('notes_to_financial_statements', 'Notes to the financial statements'),
    ('dmcc_sheet', 'Summary sheet'),
]

REQUIRED_SECTION_LABELS = {
    'table_of_contents': 'Table of contents',
    'entity_information': 'Entity information',
    'report_of_directors': 'Report of directors',
    'independent_auditor_report': 'Independent auditor report',
    'balance_sheet_page': 'Statement of financial position',
    'profit_loss': 'Statement of profit and loss',
    'changes_in_equity': 'Statement of changes in equity',
    'cash_flows': 'Statement of cash flows',
    'notes_to_financial_statements': 'Notes to the financial statements',
}

REQUIRED_SECTION_CLASSES = list(REQUIRED_SECTION_LABELS.keys())


class AuditReportDocument(models.Model):
    _name = 'audit.report.document'
    _description = 'Saved Audit Report Document'
    _order = 'id desc'

    name = fields.Char(required=True)
    company_id = fields.Many2one(
        'res.company',
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    date_start = fields.Date()
    date_end = fields.Date()
    report_type = fields.Selection(REPORT_TYPE_SELECTION)
    audit_period_category = fields.Selection(AUDIT_PERIOD_CATEGORY_SELECTION)
    source_wizard_json = fields.Text()
    tb_overrides_json = fields.Text(copy=False)
    lor_extra_items_json = fields.Text(copy=False)
    active = fields.Boolean(default=True)

    revision_ids = fields.One2many(
        'audit.report.revision',
        'document_id',
        string='Revisions',
    )
    current_revision_id = fields.Many2one(
        'audit.report.revision',
        string='Current Revision',
        readonly=True,
        copy=False,
    )
    revision_count = fields.Integer(
        compute='_compute_revision_count',
        string='Revision Count',
    )

    @api.model
    def _register_hook(self):
        """Keep rule domains in sync even if old records were loaded as noupdate."""
        result = super()._register_hook()
        domain = "[('company_id', 'in', user.company_ids.ids)]"
        self.env.cr.execute(
            """
            UPDATE ir_rule AS rule
               SET domain_force = %s,
                   active = TRUE
              FROM ir_model_data AS data
             WHERE data.model = 'ir.rule'
               AND data.module = 'Audit_Report'
               AND data.name IN %s
               AND data.res_id = rule.id
               AND (rule.domain_force IS DISTINCT FROM %s OR rule.active IS DISTINCT FROM TRUE)
            """,
            [
                domain,
                (
                    'audit_report_document_active_company_rule',
                    'audit_report_revision_active_company_rule',
                ),
                domain,
            ],
        )
        if self.env.cr.rowcount:
            self.env.registry.clear_cache()
        return result

    @api.depends('revision_ids')
    def _compute_revision_count(self):
        counts_by_document = {document_id: 0 for document_id in self.ids}
        if self.ids:
            grouped_rows = self.env['audit.report.revision']._read_group(
                domain=[('document_id', 'in', self.ids)],
                groupby=['document_id'],
                aggregates=['__count'],
            )
            for document, count in grouped_rows:
                if document:
                    counts_by_document[document.id] = count
        for record in self:
            record.revision_count = counts_by_document.get(record.id, 0)

    def action_open_revisions(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Report Revisions'),
            'res_model': 'audit.report.revision',
            'view_mode': 'list,form',
            'domain': [('document_id', '=', self.id)],
            'context': {
                'default_document_id': self.id,
                'default_company_id': self.company_id.id,
                'search_default_active_only': 1,
            },
        }

    def action_open_print_wizard(self):
        self.ensure_one()
        self._ensure_active_company()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Print Saved Revision'),
            'res_model': 'audit.report.print.wizard',
            'view_mode': 'form',
            'target': 'new',
            'context': {
                'default_document_id': self.id,
                'default_company_id': self.company_id.id,
            },
        }

    def action_open_current_preview(self):
        self.ensure_one()
        self._ensure_active_company()
        if not self.current_revision_id:
            raise ValidationError(_('No active revision available for preview.'))
        return self.current_revision_id.action_open_preview()

    def _ensure_active_company(self):
        self.ensure_one()
        user_company_ids = self.env.user.company_ids.ids
        if self.company_id.id not in user_company_ids:
            raise ValidationError(_('This report belongs to a company not allowed for your user.'))

    def _next_revision_number(self):
        self.ensure_one()
        last = self.env['audit.report.revision'].search(
            [('document_id', '=', self.id)],
            order='version_no desc',
            limit=1,
        )
        return (last.version_no or 0) + 1

    def create_revision_from_html(
        self,
        html_content,
        parent_revision=False,
        tb_overrides_json=None,
        lor_extra_items_json=None,
        wizard_snapshot_json=None,
    ):
        self.ensure_one()
        html_content = html_content or ''
        if not html_content.strip():
            raise ValidationError(_('Cannot create a revision without HTML content.'))

        if tb_overrides_json is None and parent_revision:
            tb_overrides_json = parent_revision.tb_overrides_json
        if tb_overrides_json is None:
            tb_overrides_json = self.tb_overrides_json
        tb_overrides_json = tb_overrides_json or ''

        if lor_extra_items_json is None and parent_revision:
            lor_extra_items_json = parent_revision.lor_extra_items_json
        if lor_extra_items_json is None:
            lor_extra_items_json = self.lor_extra_items_json
        lor_extra_items_json = lor_extra_items_json or ''

        if wizard_snapshot_json is None and parent_revision:
            wizard_snapshot_json = parent_revision.wizard_snapshot_json
        if wizard_snapshot_json is None:
            wizard_snapshot_json = self.source_wizard_json
        wizard_snapshot_json = wizard_snapshot_json or ''

        revision = self.env['audit.report.revision'].create({
            'document_id': self.id,
            'company_id': self.company_id.id,
            'version_no': self._next_revision_number(),
            'parent_revision_id': parent_revision.id if parent_revision else False,
            'html_content': html_content,
            'tb_overrides_json': tb_overrides_json,
            'lor_extra_items_json': lor_extra_items_json,
            'wizard_snapshot_json': wizard_snapshot_json,
        })
        if (self.tb_overrides_json or '') != tb_overrides_json:
            self.tb_overrides_json = tb_overrides_json
        if (self.lor_extra_items_json or '') != lor_extra_items_json:
            self.lor_extra_items_json = lor_extra_items_json
        self.current_revision_id = revision.id
        return revision


class AuditReportRevision(models.Model):
    _name = 'audit.report.revision'
    _description = 'Audit Report Revision'
    _order = 'version_no desc, id desc'
    _rec_name = 'display_name'

    display_name = fields.Char(compute='_compute_display_name', store=True)
    document_id = fields.Many2one(
        'audit.report.document',
        required=True,
        ondelete='cascade',
        index=True,
    )
    company_id = fields.Many2one(
        'res.company',
        required=True,
        index=True,
    )
    version_no = fields.Integer(required=True)
    parent_revision_id = fields.Many2one(
        'audit.report.revision',
        ondelete='set null',
    )
    created_by_id = fields.Many2one(
        'res.users',
        default=lambda self: self.env.user,
        readonly=True,
    )
    created_on = fields.Datetime(
        default=fields.Datetime.now,
        readonly=True,
    )

    html_content = fields.Text(required=True)
    table_index_json = fields.Text(readonly=True)
    tb_overrides_json = fields.Text(readonly=True)
    lor_extra_items_json = fields.Text(readonly=True)
    wizard_snapshot_json = fields.Text(readonly=True)
    pdf_attachment_id = fields.Many2one('ir.attachment', ondelete='set null', copy=False)
    pdf_hash = fields.Char(copy=False)
    pdf_generated_on = fields.Datetime(copy=False)

    is_removed = fields.Boolean(default=False, index=True)
    removed_by_id = fields.Many2one('res.users', readonly=True)
    removed_on = fields.Datetime(readonly=True)

    is_current = fields.Boolean(compute='_compute_is_current', string='Current')

    @api.depends('document_id.name', 'version_no')
    def _compute_display_name(self):
        for record in self:
            base = record.document_id.name or _('Saved Audit Report')
            record.display_name = f"{base} - v{record.version_no}"

    @api.depends('document_id.current_revision_id')
    def _compute_is_current(self):
        for record in self:
            record.is_current = record.document_id.current_revision_id == record

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get('document_id') and not vals.get('company_id'):
                vals['company_id'] = self.env['audit.report.document'].browse(vals['document_id']).company_id.id
            if vals.get('document_id') and not vals.get('version_no'):
                document = self.env['audit.report.document'].browse(vals['document_id'])
                vals['version_no'] = document._next_revision_number()
            if vals.get('parent_revision_id') and not vals.get('wizard_snapshot_json'):
                parent_revision = self.env['audit.report.revision'].browse(vals['parent_revision_id'])
                vals['wizard_snapshot_json'] = (
                    parent_revision.wizard_snapshot_json
                    or parent_revision.document_id.source_wizard_json
                    or ''
                )
            elif vals.get('document_id') and not vals.get('wizard_snapshot_json'):
                document = self.env['audit.report.document'].browse(vals['document_id'])
                vals['wizard_snapshot_json'] = document.source_wizard_json or ''
            if vals.get('html_content') and not vals.get('table_index_json'):
                vals['table_index_json'] = self._serialize_table_index(
                    self._extract_table_index(vals['html_content'])
                )
        records = super().create(vals_list)
        for record in records:
            if record.document_id.current_revision_id != record:
                record.document_id.current_revision_id = record.id
        return records

    def write(self, vals):
        if 'html_content' in vals and 'table_index_json' not in vals:
            for record in self:
                update_vals = dict(vals)
                update_vals['table_index_json'] = self._serialize_table_index(
                    self._extract_table_index(update_vals.get('html_content') or '')
                )
                update_vals['pdf_hash'] = False
                update_vals['pdf_generated_on'] = False
                update_vals['pdf_attachment_id'] = False
                super(AuditReportRevision, record).write(update_vals)
            return True
        return super().write(vals)

    def action_open_preview(self):
        self.ensure_one()
        self._ensure_active_company()
        return {
            'type': 'ir.actions.act_url',
            'url': f'/audit_report/revision/{self.id}/preview',
            'target': 'new',
        }

    def action_open_pdf(self):
        self.ensure_one()
        self._ensure_active_company()
        return {
            'type': 'ir.actions.act_url',
            'url': f'/audit_report/revision/{self.id}/pdf',
            'target': 'new',
        }

    def action_open_structured_editor(self):
        self.ensure_one()
        self._ensure_active_company()
        return {
            'type': 'ir.actions.act_url',
            'url': f'/audit_report/revision/{self.id}/edit/structured',
            'target': 'new',
        }

    def action_open_freeform_editor(self):
        self.ensure_one()
        self._ensure_active_company()
        return {
            'type': 'ir.actions.act_url',
            'url': f'/audit_report/revision/{self.id}/edit/freeform',
            'target': 'new',
        }

    def _build_audit_report_wizard_from_snapshot(self):
        self.ensure_one()
        self._ensure_active_company()
        snapshot_raw = (self.wizard_snapshot_json or self.document_id.source_wizard_json or '').strip()
        if not snapshot_raw:
            raise ValidationError(_('No wizard snapshot is available for this saved report.'))
        try:
            snapshot_data = json.loads(snapshot_raw)
        except (TypeError, ValueError):
            raise ValidationError(_('Wizard snapshot data is invalid JSON and cannot be opened.'))

        wizard_env = self.env['audit.report'].with_context(default_use_previous_settings=False)
        wizard_vals = wizard_env._build_wizard_vals_from_snapshot(snapshot_data)
        wizard_vals['company_id'] = self.company_id.id
        wizard_vals['use_previous_settings'] = False
        wizard_vals['audit_target_revision_id'] = self.id
        wizard_vals['audit_target_document_id'] = self.document_id.id
        wizard = wizard_env.create(wizard_vals)
        wizard._load_tb_override_lines(preserve_overrides=False)
        wizard._apply_tb_overrides_from_serialized_payload(
            self.tb_overrides_json or self.document_id.tb_overrides_json or ''
        )
        wizard._sync_tb_overrides_json()
        wizard._apply_lor_extra_items_from_serialized_payload(
            self.lor_extra_items_json
            or self.document_id.lor_extra_items_json
            or snapshot_data.get('lor_extra_items_json')
            or ''
        )
        try:
            wizard._get_report_data()
        except Exception as err:
            _logger.debug(
                "TB override warning refresh skipped for revision wizard revision_id=%s due to: %s",
                self.id,
                err,
            )
        return wizard

    def action_open_tb_override_wizard(self):
        return self._open_audit_report_wizard_form()

    def action_open_revision_settings_wizard(self):
        return self._open_audit_report_wizard_form()

    def _open_audit_report_wizard_form(self):
        wizard = self._build_audit_report_wizard_from_snapshot()

        action = self.env['ir.actions.actions']._for_xml_id('Audit_Report.audit_report_wizard_action')
        action_context = dict(self.env.context)
        action_context.update({
            'dialog_size': 'extra-large',
            'form_view_initial_mode': 'edit',
            'audit_target_revision_id': self.id,
            'audit_target_document_id': self.document_id.id,
            'default_use_previous_settings': False,
        })
        action_flags = dict(action.get('flags') or {})
        action_flags['mode'] = 'edit'
        action.update({
            'res_id': wizard.id,
            'view_mode': 'form',
            'target': 'new',
            'context': action_context,
            'flags': action_flags,
        })
        return action

    def action_open_lor_editor_wizard(self):
        self.ensure_one()
        return self._open_audit_report_wizard_form()

    def action_soft_remove(self):
        now = fields.Datetime.now()
        for record in self:
            record._ensure_active_company()
            if record.is_removed:
                continue
            record.write({
                'is_removed': True,
                'removed_by_id': self.env.user.id,
                'removed_on': now,
            })
        self.mapped('document_id')._refresh_current_revision()
        return True

    def action_restore(self):
        for record in self:
            record._ensure_active_company()
            if not record.is_removed:
                continue
            record.write({
                'is_removed': False,
                'removed_by_id': False,
                'removed_on': False,
            })
        self.mapped('document_id')._refresh_current_revision()
        return True

    def _ensure_active_company(self):
        self.ensure_one()
        user_company_ids = self.env.user.company_ids.ids
        if self.company_id.id not in user_company_ids:
            raise ValidationError(_('This revision belongs to a company not allowed for your user.'))

    @api.model
    def _serialize_table_index(self, table_index):
        return json.dumps(table_index or [], ensure_ascii=False)

    @api.model
    def _parse_html(self, html_content):
        raw = html_content or '<!doctype html><html><body></body></html>'
        parser = html.HTMLParser(encoding='utf-8', recover=True)
        try:
            return html.fromstring(raw, parser=parser)
        except Exception:
            return html.fromstring('<!doctype html><html><body></body></html>', parser=parser)

    @api.model
    def _module_root_path(self):
        return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

    @api.model
    def _get_report_css_content(self):
        css_path = os.path.join(self._module_root_path(), 'templates', 'audit_report_style.css')
        try:
            with open(css_path, 'r', encoding='utf-8') as css_file:
                return css_file.read()
        except Exception:
            return ''

    @api.model
    def _normalize_document_root(self, root):
        if not isinstance(getattr(root, 'tag', None), str) or (root.tag or '').lower() != 'html':
            html_root = etree.Element('html')
            head = etree.Element('head')
            body = etree.Element('body')
            html_root.append(head)
            html_root.append(body)

            if root is not None:
                root_tag = (getattr(root, 'tag', '') or '').lower() if isinstance(getattr(root, 'tag', None), str) else ''
                if root_tag == 'head':
                    for child in list(root):
                        head.append(copy.deepcopy(child))
                elif root_tag == 'body':
                    for key, value in root.attrib.items():
                        body.set(key, value)
                    for child in list(root):
                        body.append(copy.deepcopy(child))
                else:
                    body.append(copy.deepcopy(root))
            root = html_root

        heads = root.xpath('./head')
        bodies = root.xpath('./body')

        if heads:
            head = heads[0]
        else:
            head = etree.Element('head')
            root.insert(0, head)

        if bodies:
            body = bodies[0]
        else:
            body = etree.Element('body')
            root.append(body)

        for child in list(root):
            if child is head or child is body:
                continue
            root.remove(child)
            body.append(child)

        return root

    @api.model
    def _sanitize_root(self, root):
        for node in root.xpath('//script'):
            parent = node.getparent()
            if parent is not None:
                parent.remove(node)

        for element in root.iter():
            for attr_name in list(element.attrib):
                attr_lower = attr_name.lower()
                attr_value = element.attrib.get(attr_name) or ''
                if attr_lower.startswith('on'):
                    del element.attrib[attr_name]
                elif attr_lower in ('href', 'src') and str(attr_value).strip().lower().startswith('javascript:'):
                    element.attrib[attr_name] = ''
        return root

    @api.model
    def _serialize_document_html(self, root):
        rendered = etree.tostring(root, encoding='unicode', method='html')
        return f'<!doctype html>\n{rendered}'

    @api.model
    def _has_class(self, node, class_name):
        classes = (node.get('class') or '').split()
        return class_name in classes

    @api.model
    def _find_section_by_class(self, root, class_name):
        for section in root.xpath('//section'):
            if self._has_class(section, class_name):
                return section
        return None

    @api.model
    def _cell_visual_lines(self, cell):
        """Return user-visible cell lines, treating editor breaks as row hints."""
        lines = ['']

        def append_text(value):
            value = (value or '').replace('\r', '').replace('\xa0', ' ')
            if not value:
                return
            parts = value.split('\n')
            for index, part in enumerate(parts):
                if index:
                    lines.append('')
                lines[-1] += part

        def append_line_break():
            if lines[-1].strip():
                lines.append('')

        def walk(node):
            append_text(node.text)
            for child in node:
                tag_name = (child.tag or '').lower() if isinstance(getattr(child, 'tag', None), str) else ''
                if tag_name == 'br':
                    append_line_break()
                    append_text(child.tail)
                    continue

                if tag_name in ('div', 'p'):
                    append_line_break()
                    walk(child)
                    append_line_break()
                    append_text(child.tail)
                    continue

                walk(child)
                append_text(child.tail)

        walk(cell)

        cleaned = [re.sub(r'[ \t\f\v]+', ' ', line).strip() for line in lines]
        while cleaned and not cleaned[0]:
            cleaned.pop(0)
        while cleaned and not cleaned[-1]:
            cleaned.pop()
        return cleaned or ['']

    @api.model
    def _is_cashflow_detail_row(self, row):
        row_class = (row.get('class') or '').split()
        blocked_classes = {
            'section-row',
            'subsection-row',
            'total-row',
            'grand-total-row',
            'cash-flow-ending',
        }
        if blocked_classes.intersection(row_class):
            return False
        if row.xpath('./th'):
            return False
        cells = row.xpath('./td')
        if len(cells) < 3:
            return False
        if row.xpath('.//*[contains(concat(" ", normalize-space(@class), " "), " amount-line ")]'):
            return False
        return True

    @api.model
    def _clone_plain_table_cell(self, cell):
        attributes = {
            key: value
            for key, value in cell.attrib.items()
            if key not in ('id', 'rowspan')
        }
        return etree.Element(cell.tag, **attributes)

    @api.model
    def _normalize_cashflow_multiline_detail_rows(self, root):
        """Split edited cashflow detail rows that contain visual line breaks.

        This keeps cashflow-only manual additions such as "IT equipment" behaving
        like normal statement rows instead of stacked text inside one row.
        """
        cashflow_sections = [
            section
            for section in root.xpath('//section')
            if self._has_class(section, 'cash_flows')
        ]
        for section in cashflow_sections:
            for table in section.xpath('.//table'):
                if not self._has_class(table, 'statement-table'):
                    continue

                for row in list(table.xpath('./tbody/tr|./tr')):
                    if not self._is_cashflow_detail_row(row):
                        continue

                    cells = row.xpath('./td')
                    cell_lines = [self._cell_visual_lines(cell) for cell in cells]
                    line_count = max((len(lines) for lines in cell_lines), default=1)
                    if line_count <= 1:
                        continue

                    parent = row.getparent()
                    if parent is None:
                        continue

                    insert_at = parent.index(row)
                    row_attrs = {
                        key: value
                        for key, value in row.attrib.items()
                        if key != 'id'
                    }
                    for line_index in range(line_count):
                        new_row = etree.Element('tr', **row_attrs)
                        for cell, lines in zip(cells, cell_lines):
                            new_cell = self._clone_plain_table_cell(cell)
                            new_cell.text = lines[line_index] if line_index < len(lines) else ''
                            new_row.append(new_cell)
                        parent.insert(insert_at + line_index, new_row)
                    parent.remove(row)

    @api.model
    def _find_table_by_class(self, root, class_name):
        for table in root.xpath('.//table'):
            if self._has_class(table, class_name):
                return table
        return None

    @api.model
    def _normalize_toc_label(self, text):
        value = re.sub(r'\s+', ' ', (text or '').strip().lower())
        value = re.sub(r'[^a-z0-9 ]+', '', value)
        return value.strip()

    @api.model
    def _validate_required_sections(self, root):
        missing = []
        for class_name in REQUIRED_SECTION_CLASSES:
            if self._find_section_by_class(root, class_name) is None:
                missing.append(REQUIRED_SECTION_LABELS.get(class_name, class_name))

        if missing:
            bullet_lines = '\n'.join(f'- {label}' for label in missing)
            raise ValidationError(
                _('Edited report is missing required sections:\n%s') % bullet_lines
            )

    @api.model
    def _ensure_report_style_block(self, root):
        head = root.xpath('./head')[0]
        existing_styles = head.xpath('./style')
        has_report_style = False
        for style_node in existing_styles:
            style_text = ''.join(style_node.itertext() or [])
            if '@page' in style_text and '.table_of_contents' in style_text:
                has_report_style = True
                break

        if has_report_style:
            return

        css_content = self._get_report_css_content()
        if not css_content.strip():
            return

        style_node = etree.Element('style')
        style_node.set('data-audit-report-style', '1')
        style_node.text = css_content
        head.append(style_node)

    @api.model
    def _ensure_toc_table_structure(self, root):
        toc_section = self._find_section_by_class(root, 'table_of_contents')
        if toc_section is None:
            return None

        toc_table = self._find_table_by_class(toc_section, 'toc-table')
        if toc_table is None:
            toc_table = etree.Element('table')
            toc_table.set('class', 'toc-table')
            toc_section.append(toc_table)

        tbodies = toc_table.xpath('./tbody')
        if tbodies:
            tbody = tbodies[0]
        else:
            tbody = etree.Element('tbody')
            for direct_row in toc_table.xpath('./tr'):
                toc_table.remove(direct_row)
                tbody.append(direct_row)
            toc_table.append(tbody)

        rows = tbody.xpath('./tr')
        if not rows:
            for section_class, label in TOC_SECTION_SEQUENCE:
                section = self._find_section_by_class(root, section_class)
                if section is None:
                    continue
                row = etree.Element('tr')
                label_cell = etree.Element('td')
                page_cell = etree.Element('td')
                label_cell.text = label
                page_cell.text = ''
                row.append(label_cell)
                row.append(page_cell)
                tbody.append(row)
            rows = tbody.xpath('./tr')

        for row in rows:
            cells = row.xpath('./th|./td')
            if not cells:
                row.append(etree.Element('td'))
                row.append(etree.Element('td'))
                continue
            if len(cells) == 1:
                tag_name = (cells[0].tag or '').lower()
                new_cell = etree.Element(tag_name if tag_name in ('th', 'td') else 'td')
                row.append(new_cell)

        return toc_table

    @api.model
    def _set_toc_row_page_range(self, row, page_range, label_fallback=''):
        cells = row.xpath('./th|./td')
        if not cells:
            label_cell = etree.Element('td')
            page_cell = etree.Element('td')
            row.append(label_cell)
            row.append(page_cell)
            cells = [label_cell, page_cell]
        elif len(cells) == 1:
            tag_name = (cells[0].tag or '').lower()
            page_cell = etree.Element(tag_name if tag_name in ('th', 'td') else 'td')
            row.append(page_cell)
            cells = row.xpath('./th|./td')

        if label_fallback and not ''.join(cells[0].itertext()).strip():
            cells[0].text = label_fallback
        cells[1].text = page_range or ''

    @api.model
    def _present_toc_sections(self, root):
        present = []
        for section_class, label in TOC_SECTION_SEQUENCE:
            section = self._find_section_by_class(root, section_class)
            if section is not None:
                present.append((section_class, label))
        return present

    @api.model
    def _build_single_section_html(self, root, section_class):
        section = self._find_section_by_class(root, section_class)
        if section is None:
            return ''

        head = root.xpath('./head')[0]
        source_body = root.xpath('./body')[0]
        doc_root = etree.Element('html')
        doc_head = copy.deepcopy(head)
        doc_body = etree.Element('body')
        for key, value in source_body.attrib.items():
            doc_body.set(key, value)
        doc_body.append(copy.deepcopy(section))
        doc_root.append(doc_head)
        doc_root.append(doc_body)
        return self._serialize_document_html(doc_root)

    @api.model
    def _build_revision_section_anchor_map(self, root):
        used_ids = {
            element_id.strip()
            for element_id in root.xpath('//@id')
            if isinstance(element_id, str) and element_id.strip()
        }
        anchor_map = []
        for section_class, label in self._present_toc_sections(root):
            section = self._find_section_by_class(root, section_class)
            if section is None:
                continue

            base_id = f'audit-revision-anchor-{section_class}'
            anchor_id = base_id
            suffix = 2
            while anchor_id in used_ids:
                anchor_id = f'{base_id}-{suffix}'
                suffix += 1
            used_ids.add(anchor_id)

            anchor_node = etree.Element('a')
            anchor_node.set('id', anchor_id)
            anchor_node.set(
                'style',
                'display:block;height:0;line-height:0;overflow:hidden;margin:0;padding:0;',
            )
            section.insert(0, anchor_node)
            anchor_map.append(
                {
                    'section_class': section_class,
                    'label': label,
                    'anchor_id': anchor_id,
                }
            )
        return anchor_map

    @api.model
    def _extract_anchor_start_pages(self, doc):
        anchor_pages = {}
        pages = getattr(doc, 'pages', []) or []
        for page_index, page in enumerate(pages, start=1):
            anchors = getattr(page, 'anchors', {}) or {}
            for anchor_name in anchors.keys():
                if anchor_name and anchor_name not in anchor_pages:
                    anchor_pages[anchor_name] = page_index
        return anchor_pages

    @api.model
    def _compute_revision_toc_entries_legacy(self, root):
        from ..controllers.main import AuditReportController

        controller = AuditReportController()
        module_path = self._module_root_path()
        toc_entries = []
        current_page = 1
        for section_class, label in self._present_toc_sections(root):
            section_html = self._build_single_section_html(root, section_class)
            if not section_html.strip():
                continue

            doc = controller._html_to_pdf_doc(section_html, base_url=module_path)
            page_count = len(doc.pages)
            if page_count <= 0:
                continue

            end_page = current_page + page_count - 1
            page_range = str(current_page) if page_count == 1 else f'{current_page}-{end_page}'
            toc_entries.append({'label': label, 'page_range': page_range})
            current_page = end_page + 1

        return toc_entries

    @api.model
    def _compute_revision_toc_entries_from_full_doc(self, root):
        from ..controllers.main import AuditReportController

        working_root = copy.deepcopy(root)
        section_anchors = self._build_revision_section_anchor_map(working_root)
        if not section_anchors:
            return []

        controller = AuditReportController()
        module_path = self._module_root_path()
        full_html = self._serialize_document_html(working_root)
        doc = controller._html_to_pdf_doc(full_html, base_url=module_path)
        pages = getattr(doc, 'pages', []) or []
        if not pages:
            return []

        anchor_pages = self._extract_anchor_start_pages(doc)
        if not anchor_pages:
            raise RuntimeError('No section anchors were detected in the rendered revision document.')

        entity_anchor = next(
            (
                row['anchor_id']
                for row in section_anchors
                if row.get('section_class') == 'entity_information'
            ),
            '',
        )
        entity_start_page = anchor_pages.get(entity_anchor, 1)

        def _display_page(physical_page):
            return max(1, physical_page - entity_start_page + 1)

        toc_entries = []
        total_pages = len(pages)
        for index, row in enumerate(section_anchors):
            start_page = anchor_pages.get(row.get('anchor_id'))
            if start_page is None:
                continue

            next_start_page = None
            for later in section_anchors[index + 1:]:
                later_start = anchor_pages.get(later.get('anchor_id'))
                if later_start is not None:
                    next_start_page = later_start
                    break

            if next_start_page is None:
                end_page = total_pages
            else:
                end_page = max(start_page, next_start_page - 1)

            display_start = _display_page(start_page)
            display_end = max(display_start, _display_page(end_page))
            page_range = (
                str(display_start)
                if display_start == display_end
                else f'{display_start}-{display_end}'
            )
            toc_entries.append({'label': row.get('label') or '', 'page_range': page_range})
        return toc_entries

    def _compute_revision_toc_entries(self, root):
        try:
            return self._compute_revision_toc_entries_from_full_doc(root)
        except Exception as e:
            _logger.exception(
                "Revision TOC anchor-based pagination failed; falling back to legacy method: %s",
                e,
            )
            return self._compute_revision_toc_entries_legacy(root)

    @api.model
    def _apply_toc_entries(self, root, toc_entries):
        toc_table = self._ensure_toc_table_structure(root)
        if toc_table is None:
            return

        tbody = toc_table.xpath('./tbody')[0]
        rows = tbody.xpath('./tr')
        row_labels = [
            self._normalize_toc_label(' '.join((row.xpath('./th|./td')[0]).itertext()))
            if row.xpath('./th|./td') else ''
            for row in rows
        ]
        assigned = set()

        for index, entry in enumerate(toc_entries):
            label = entry.get('label') or ''
            page_range = entry.get('page_range') or ''
            normalized_label = self._normalize_toc_label(label)
            chosen_index = None

            if index < len(rows) and index not in assigned:
                candidate_label = row_labels[index]
                if not candidate_label or candidate_label == normalized_label:
                    chosen_index = index

            if chosen_index is None:
                for row_index, row_label in enumerate(row_labels):
                    if row_index in assigned:
                        continue
                    if row_label and row_label == normalized_label:
                        chosen_index = row_index
                        break

            if chosen_index is None and index < len(rows) and index not in assigned:
                chosen_index = index

            if chosen_index is None:
                new_row = etree.Element('tr')
                label_cell = etree.Element('td')
                page_cell = etree.Element('td')
                new_row.append(label_cell)
                new_row.append(page_cell)
                tbody.append(new_row)
                rows.append(new_row)
                row_labels.append('')
                chosen_index = len(rows) - 1

            self._set_toc_row_page_range(rows[chosen_index], page_range, label_fallback=label)
            assigned.add(chosen_index)

        for row_index, row in enumerate(rows):
            if row_index in assigned:
                continue
            self._set_toc_row_page_range(row, '')

    def _prepare_revision_html(self, html_content, refresh_toc=False):
        root = self._parse_html(html_content)
        root = self._normalize_document_root(root)
        root = self._sanitize_root(root)
        self._normalize_cashflow_multiline_detail_rows(root)
        self._ensure_report_style_block(root)
        self._validate_required_sections(root)
        self._ensure_toc_table_structure(root)

        if refresh_toc:
            try:
                toc_entries = self._compute_revision_toc_entries(root)
                self._apply_toc_entries(root, toc_entries)
            except Exception as e:
                _logger.exception(
                    "Revision TOC refresh failed; existing TOC entries were kept: %s",
                    e,
                )

        return self._serialize_document_html(root)

    def prepare_edited_html_for_storage(self, html_content):
        self.ensure_one()
        self._ensure_active_company()
        return self._prepare_revision_html(html_content or '', refresh_toc=False)

    def _build_render_ready_html(self, refresh_toc=True):
        self.ensure_one()
        self._ensure_active_company()
        return self._prepare_revision_html(self.html_content or '', refresh_toc=refresh_toc)

    @api.model
    def _iter_tables(self, root):
        section_counter = {}
        for global_index, table in enumerate(root.xpath('//table'), start=1):
            section_name = 'document'
            parent = table
            while parent is not None:
                tag_name = getattr(parent, 'tag', '')
                if isinstance(tag_name, str) and tag_name.lower() == 'section':
                    classes = (parent.get('class') or '').split()
                    section_name = classes[0] if classes else 'section'
                    break
                parent = parent.getparent()

            section_index = section_counter.get(section_name, 0) + 1
            section_counter[section_name] = section_index
            table_key = f'{section_name}:{section_index}'
            yield global_index, table_key, section_name, section_index, table

    @api.model
    def _direct_rows(self, table):
        rows = table.xpath('./thead/tr|./tbody/tr|./tfoot/tr|./tr')
        return rows or table.xpath('.//tr')

    @api.model
    def _table_has_nested_tables(self, table):
        return bool(table.xpath('./descendant::table'))

    @api.model
    def _extract_table_index(self, html_content):
        root = self._parse_html(html_content)
        table_index = []
        for global_index, table_key, section_name, section_index, table in self._iter_tables(root):
            has_nested_tables = self._table_has_nested_tables(table)
            is_nested_within_table = bool(table.xpath('./ancestor::table'))
            table_class = (table.get('class') or '').strip()
            rows = self._direct_rows(table)
            row_count = len(rows)
            col_count = 0
            preview = ''

            for row in rows:
                cells = row.xpath('./th|./td')
                col_span_count = 0
                cell_texts = []
                for cell in cells:
                    span_raw = cell.get('colspan') or '1'
                    try:
                        col_span_count += max(int(span_raw), 1)
                    except ValueError:
                        col_span_count += 1
                    text_value = ' '.join(cell.itertext()).strip()
                    if text_value:
                        cell_texts.append(text_value)
                col_count = max(col_count, col_span_count)
                if not preview and cell_texts:
                    preview = ' | '.join(cell_texts[:3])[:160]

            table_index.append({
                'key': table_key,
                'section': section_name,
                'table_index': section_index,
                'global_index': global_index,
                'rows': row_count,
                'cols': col_count,
                'preview': preview,
                'has_nested_tables': has_nested_tables,
                'is_nested_within_table': is_nested_within_table,
                'table_class': table_class,
            })

        return table_index

    def get_table_index(self):
        self.ensure_one()
        # Recompute live to keep editor table keys aligned with current HTML.
        return self._extract_table_index(self.html_content or '')

    def _find_table(self, root, table_key):
        for _global_index, key, _section_name, _section_index, table in self._iter_tables(root):
            if key == table_key:
                return table
        return None

    def get_table_payload(self, table_key):
        self.ensure_one()
        root = self._parse_html(self.html_content)
        table = self._find_table(root, table_key)
        if table is None:
            return None
        if self._is_soce_table_key(table_key):
            self._normalize_soce_header_cells(table)

        row_data = []
        direct_rows = self._direct_rows(table)
        body_rows = self._tbody_rows(table)
        body_row_ids = {id(row) for row in body_rows}
        body_row_indices = []
        body_row_parent_groups = {}
        parent_group_map = {}
        next_parent_group = 1
        header_row_ids = {id(row) for row in table.xpath('./thead/tr')}
        for row_index, row in enumerate(direct_rows):
            is_header_row = id(row) in header_row_ids
            if id(row) in body_row_ids:
                body_row_indices.append(row_index)
                parent = row.getparent()
                parent_id = id(parent) if parent is not None else 0
                if parent_id not in parent_group_map:
                    parent_group_map[parent_id] = next_parent_group
                    next_parent_group += 1
                body_row_parent_groups[row_index] = parent_group_map[parent_id]
            cell_values = []
            for col_index, cell in enumerate(row.xpath('./th|./td')):
                is_editable = self._is_simple_editable_cell(cell)
                if cell.xpath('./descendant::table'):
                    value = '[Nested table content]'
                else:
                    value = ' '.join(cell.itertext()).strip()
                cell_values.append({
                    'r': row_index,
                    'c': col_index,
                    'name': f'cell_{row_index}_{col_index}',
                    'value': value,
                    'tag': (cell.tag or '').lower(),
                    'is_header_row': is_header_row,
                    'editable': is_editable,
                })
            row_data.append(cell_values)

        return {
            'table_key': table_key,
            'rows': row_data,
            'body_row_count': len(body_rows),
            'body_row_indices': body_row_indices,
            'body_row_parent_groups': body_row_parent_groups,
        }

    @api.model
    def _safe_span(self, cell, attr_name='colspan'):
        raw = (cell.get(attr_name) or '').strip()
        try:
            span = int(raw)
        except (TypeError, ValueError):
            span = 1
        return max(span, 1)

    @api.model
    def _set_colspan(self, cell, span):
        if span <= 1:
            cell.attrib.pop('colspan', None)
        else:
            cell.set('colspan', str(span))

    @api.model
    def _row_visual_col_count(self, row):
        cells = row.xpath('./th|./td')
        return sum(self._safe_span(cell, 'colspan') for cell in cells)

    @api.model
    def _tbody_rows(self, table):
        rows = table.xpath('./tbody/tr')
        if rows:
            return rows
        # Fallback tables without explicit tbody.
        return table.xpath('./tr')

    @api.model
    def _table_body_container(self, table):
        bodies = table.xpath('./tbody')
        return bodies[0] if bodies else table

    @api.model
    def _is_soce_table_key(self, table_key):
        return (table_key or '').startswith('changes_in_equity:')

    @api.model
    def _locate_cell_by_visual_col(self, cells, target_col):
        """Find the cell covering a 1-based visual column index."""
        if not cells:
            return {
                'index': -1,
                'cell': None,
                'start': 1,
                'end': 1,
                'span': 1,
            }

        cursor = 1
        last = None
        for idx, cell in enumerate(cells):
            span = self._safe_span(cell, 'colspan')
            start = cursor
            end = cursor + span - 1
            last = {
                'index': idx,
                'cell': cell,
                'start': start,
                'end': end,
                'span': span,
            }
            if target_col <= end:
                return last
            cursor = end + 1
        return last

    @api.model
    def _clear_node_text(self, node):
        for child in node.iter():
            if isinstance(getattr(child, 'tag', None), str):
                child.text = ''
                child.tail = ''
                if child.tag.lower() == 'input':
                    child.set('value', '')
        return node

    @api.model
    def _clone_cell_like(self, cell):
        """Clone cell style/structure while clearing textual content for insertion."""
        cloned = copy.deepcopy(cell)
        if 'id' in cloned.attrib:
            del cloned.attrib['id']
        for element in cloned.xpath('.//*[@id]'):
            if 'id' in element.attrib:
                del element.attrib['id']
        # Prevent cloned rows from creating broken rowspan grids.
        cloned.attrib.pop('rowspan', None)
        return self._clear_node_text(cloned)

    @api.model
    def _clone_row_like(self, row):
        row_attrs = {key: value for key, value in row.attrib.items() if key != 'id'}
        cloned_row = etree.Element('tr', **row_attrs)
        cells = row.xpath('./th|./td')
        if not cells:
            blank = etree.Element('td')
            blank.text = ''
            cloned_row.append(blank)
            return cloned_row
        for cell in cells:
            cloned_row.append(self._clone_cell_like(cell))
        return cloned_row

    @api.model
    def _is_simple_editable_cell(self, cell):
        """Allow structured edits only for simple text cells."""
        if cell.xpath('./descendant::table'):
            return False

        blocked_tags = {
            'table', 'thead', 'tbody', 'tfoot', 'tr', 'td', 'th',
            'div', 'section', 'article', 'p', 'ul', 'ol', 'li',
        }
        for child in cell:
            tag_name = (child.tag or '').lower() if isinstance(getattr(child, 'tag', None), str) else ''
            if tag_name in blocked_tags:
                return False
        return True

    @api.model
    def _set_cell_display_value(self, cell, new_value):
        """Update displayed value without destroying known formatting wrappers."""
        value = '' if new_value is None else str(new_value)
        children = list(cell)
        if not children:
            cell.text = value
            return

        if len(children) == 1:
            child = children[0]
            tag_name = (child.tag or '').lower() if isinstance(getattr(child, 'tag', None), str) else ''
            if tag_name == 'br':
                normalized = value.replace('\r', '').strip()
                if '\n' in normalized:
                    top_text, bottom_text = normalized.split('\n', 1)
                elif ' ' in normalized:
                    top_text, bottom_text = normalized.rsplit(' ', 1)
                else:
                    top_text, bottom_text = normalized, '\u00a0'
                cell.text = top_text
                child.tail = bottom_text
                return
            if tag_name in ('span', 'strong', 'b', 'i', 'em', 'u', 'a'):
                child.text = value
                return

        # Fallback for unknown mixed markup: flatten to plain text.
        for child in children:
            cell.remove(child)
        cell.text = value

    @api.model
    def _build_soce_blank_row(self):
        return self._build_soce_blank_row_with_amount_cols(3)

    @api.model
    def _build_soce_blank_row_with_amount_cols(self, amount_cols):
        row = etree.Element('tr')
        label_cell = etree.Element('td')
        label_cell.set('class', 'text-left')
        label_cell.text = ''
        row.append(label_cell)

        for _ in range(max(amount_cols, 1)):
            row.append(self._build_soce_amount_cell())

        return row

    @api.model
    def _build_soce_amount_cell(self, row=None):
        row_class = (row.get('class') or '') if row is not None else ''
        amount_cell = etree.Element('td')
        amount_cell.set('class', 'text-right')

        if 'soce-final' in row_class:
            span = etree.Element('span')
            span.set('class', 'amount-line amount-line-double')
            span.text = '-'
            amount_cell.append(span)
        elif 'soce-balance' in row_class:
            span = etree.Element('span')
            span.set('class', 'amount-line amount-line-single')
            span.text = '-'
            amount_cell.append(span)
        else:
            amount_cell.text = '-'
        return amount_cell

    @api.model
    def _soce_header_row(self, table):
        header_rows = table.xpath('./thead/tr')
        if header_rows:
            return header_rows[-1]
        fallback = table.xpath('./tbody/tr|./tr')
        return fallback[0] if fallback else None

    @api.model
    def _ensure_thead(self, table):
        heads = table.xpath('./thead')
        if heads:
            return heads[0]
        thead = etree.Element('thead')
        table.insert(0, thead)
        return thead

    @api.model
    def _ensure_soce_header_row(self, table):
        header_row = self._soce_header_row(table)
        if header_row is None:
            return None
        parent = header_row.getparent()
        parent_tag = (parent.tag or '').lower() if isinstance(getattr(parent, 'tag', None), str) else ''
        if parent_tag == 'thead':
            return header_row

        thead = self._ensure_thead(table)
        if parent is not None:
            parent.remove(header_row)
        thead.append(header_row)
        if parent is not None and parent_tag == 'tbody' and len(parent) == 0:
            grand_parent = parent.getparent()
            if grand_parent is not None:
                grand_parent.remove(parent)
        return header_row

    @api.model
    def _normalize_soce_header_cells(self, table):
        header_row = self._ensure_soce_header_row(table)
        if header_row is None:
            return None

        header_cells = header_row.xpath('./th|./td')
        for index, header_cell in enumerate(header_cells):
            if index == 0:
                continue

            if (header_cell.tag or '').lower() != 'th':
                header_cell.tag = 'th'

            class_tokens = [token for token in (header_cell.get('class') or '').split() if token]
            for required in ('text-right', 'soce-head'):
                if required not in class_tokens:
                    class_tokens.append(required)
            header_cell.set('class', ' '.join(class_tokens))

            has_br = any(
                (child.tag or '').lower() == 'br'
                for child in header_cell
                if isinstance(getattr(child, 'tag', None), str)
            )
            if has_br:
                for child in header_cell:
                    if not isinstance(getattr(child, 'tag', None), str):
                        continue
                    if (child.tag or '').lower() != 'br':
                        continue
                    if not (child.tail or '').strip():
                        child.tail = '\u00a0'
                    break
                continue

            text_value = ' '.join(header_cell.itertext()).strip()
            if ' ' in text_value:
                top_text, bottom_text = text_value.rsplit(' ', 1)
            elif text_value:
                top_text, bottom_text = text_value, '\u00a0'
            else:
                top_text, bottom_text = '', '\u00a0'
            for child in list(header_cell):
                header_cell.remove(child)
            header_cell.text = top_text
            br = etree.Element('br')
            br.tail = bottom_text
            header_cell.append(br)
        return header_row

    @api.model
    def _build_soce_header_cell(self, source_cell=None):
        header_cell = self._clone_cell_like(source_cell) if source_cell is not None else etree.Element('th')
        if (header_cell.tag or '').lower() != 'th':
            header_cell.tag = 'th'

        header_cell.attrib.pop('rowspan', None)
        header_cell.attrib.pop('colspan', None)
        class_tokens = [token for token in (header_cell.get('class') or '').split() if token]
        for required in ('text-right', 'soce-head'):
            if required not in class_tokens:
                class_tokens.append(required)
        header_cell.set('class', ' '.join(class_tokens))

        for child in list(header_cell):
            header_cell.remove(child)
        header_cell.text = 'New'
        br = etree.Element('br')
        br.tail = 'Column'
        header_cell.append(br)
        return header_cell

    def _apply_soce_add_column(self, table, target_col):
        body_rows = self._tbody_rows(table)
        header_row = self._normalize_soce_header_cells(table)
        header_col_count = self._row_visual_col_count(header_row) if header_row is not None else 0
        target_col = min(max(target_col, 1), max(header_col_count, 1))

        if header_row is not None:
            header_cells = header_row.xpath('./th|./td')
            header_loc = self._locate_cell_by_visual_col(header_cells, target_col)
            source_header_cell = header_loc['cell'] if header_loc['cell'] is not None else (header_cells[-1] if header_cells else None)
            new_header_cell = self._build_soce_header_cell(source_header_cell)
            if header_loc['cell'] is None:
                header_row.append(new_header_cell)
            elif header_loc['span'] > 1 and target_col < header_loc['end']:
                self._set_colspan(header_loc['cell'], header_loc['span'] + 1)
            else:
                header_row.insert(header_loc['index'] + 1, new_header_cell)

        for row in body_rows:
            cells = row.xpath('./th|./td')
            row_col_count = self._row_visual_col_count(row)
            col_for_row = min(max(target_col, 1), max(row_col_count, 1))
            loc = self._locate_cell_by_visual_col(cells, col_for_row)
            anchor_cell = loc['cell']
            if anchor_cell is None:
                row.append(self._build_soce_amount_cell(row))
            elif loc['span'] > 1 and col_for_row < loc['end']:
                self._set_colspan(anchor_cell, loc['span'] + 1)
            else:
                row.insert(loc['index'] + 1, self._build_soce_amount_cell(row))

    def _apply_soce_remove_column(self, table, target_col):
        body_rows = self._tbody_rows(table)
        header_row = self._normalize_soce_header_cells(table)
        header_col_count = self._row_visual_col_count(header_row) if header_row is not None else 0
        body_col_count = max((self._row_visual_col_count(row) for row in body_rows), default=0)
        col_count = max(header_col_count, body_col_count)

        if col_count <= 2:
            raise ValidationError(
                _('Statement of Changes in Equity must keep at least one amount column.')
            )
        if target_col <= 1:
            raise ValidationError(
                _('The first SOCE column is description and cannot be removed.')
            )
        target_col = min(max(target_col, 2), col_count)

        rows_to_update = []
        if header_row is not None:
            rows_to_update.append(header_row)
        rows_to_update.extend(body_rows)

        for row in rows_to_update:
            cells = row.xpath('./th|./td')
            row_col_count = self._row_visual_col_count(row)
            if row_col_count <= 1:
                continue
            col_for_row = min(max(target_col, 2), row_col_count)
            loc = self._locate_cell_by_visual_col(cells, col_for_row)
            target_cell = loc['cell']
            if target_cell is None:
                continue
            if loc['span'] > 1:
                self._set_colspan(target_cell, loc['span'] - 1)
            elif len(cells) > 1:
                row.remove(target_cell)

    @api.model
    def _parse_structured_row_order(self, row_order):
        if not row_order:
            return []

        if isinstance(row_order, (list, tuple)):
            raw_parts = row_order
        else:
            raw_parts = str(row_order).split(',')

        parsed = []
        for part in raw_parts:
            try:
                parsed.append(int(str(part).strip()))
            except (TypeError, ValueError):
                continue
        return parsed

    def _apply_structured_body_row_order(self, table, row_order):
        requested_indices = self._parse_structured_row_order(row_order)
        if not requested_indices:
            return

        direct_rows = self._direct_rows(table)
        body_rows = self._tbody_rows(table)
        if len(body_rows) <= 1:
            return

        body_row_ids = {id(row) for row in body_rows}
        index_to_body_row = {
            index: row
            for index, row in enumerate(direct_rows)
            if id(row) in body_row_ids
        }
        if len(index_to_body_row) <= 1:
            return

        ordered_indices = []
        for index in requested_indices:
            if index in index_to_body_row and index not in ordered_indices:
                ordered_indices.append(index)
        for index in index_to_body_row:
            if index not in ordered_indices:
                ordered_indices.append(index)

        if len(ordered_indices) <= 1:
            return

        requested_position = {
            index: position
            for position, index in enumerate(ordered_indices)
        }

        rows_by_parent = {}
        for index, row in index_to_body_row.items():
            parent = row.getparent()
            if parent is None:
                continue
            rows_by_parent.setdefault(parent, []).append((index, row))

        for parent, parent_rows in rows_by_parent.items():
            if len(parent_rows) <= 1:
                continue

            reordered = sorted(
                parent_rows,
                key=lambda pair: requested_position.get(pair[0], len(requested_position)),
            )
            current_rows = [row for _index, row in parent_rows]
            reordered_rows = [row for _index, row in reordered]
            if current_rows == reordered_rows:
                continue

            for row in current_rows:
                parent.remove(row)
            for row in reordered_rows:
                parent.append(row)

    def apply_structured_table_changes(self, table_key, posted_cells, table_action='save', target_row=0, target_col=0, row_order=''):
        self.ensure_one()
        root = self._parse_html(self.html_content)
        table = self._find_table(root, table_key)
        if table is None:
            raise ValidationError(_('The selected table no longer exists in this revision.'))
        table_action = (table_action or 'save').strip().lower()
        is_soce = self._is_soce_table_key(table_key)
        if is_soce:
            self._normalize_soce_header_cells(table)

        for row_index, row in enumerate(self._direct_rows(table)):
            cells = row.xpath('./th|./td')
            for col_index, cell in enumerate(cells):
                field_name = f'cell_{row_index}_{col_index}'
                if field_name not in posted_cells:
                    continue
                if not self._is_simple_editable_cell(cell):
                    continue

                new_value = posted_cells.get(field_name, '')
                current_value = ' '.join(cell.itertext()).strip()
                if str(new_value).strip() == current_value:
                    continue
                self._set_cell_display_value(cell, new_value)

        self._apply_structured_body_row_order(table, row_order)

        rows = self._direct_rows(table)
        body_rows = self._tbody_rows(table)
        row_count = len(rows)
        body_row_count = len(body_rows)
        col_count = max((self._row_visual_col_count(row) for row in rows), default=0)

        def _safe_int(value, default=0):
            try:
                return int(value or default)
            except (TypeError, ValueError):
                return default

        target_row = _safe_int(target_row, body_row_count)
        target_col = _safe_int(target_col, col_count)

        if table_action == 'add_row_after':
            if not body_rows:
                parent = self._table_body_container(table)
                new_row = etree.Element('tr')
                new_cell = etree.Element('td')
                new_cell.text = ''
                new_row.append(new_cell)
                parent.append(new_row)
            else:
                target_row = min(max(target_row, 1), body_row_count)
                anchor_row = body_rows[target_row - 1]
                if is_soce:
                    amount_cols = max(col_count - 1, 1)
                    new_row = self._build_soce_blank_row_with_amount_cols(amount_cols)
                else:
                    new_row = self._clone_row_like(anchor_row)
                parent = anchor_row.getparent()
                parent.insert(parent.index(anchor_row) + 1, new_row)

        elif table_action == 'remove_row':
            if body_row_count > 1:
                target_row = min(max(target_row, 1), body_row_count)
                target = body_rows[target_row - 1]
                parent = target.getparent()
                parent.remove(target)

        elif table_action == 'add_col_after':
            if is_soce:
                self._apply_soce_add_column(table, target_col)
            elif not rows:
                new_row = etree.Element('tr')
                new_cell = etree.Element('td')
                new_cell.text = ''
                new_row.append(new_cell)
                table.append(new_row)
            else:
                if col_count <= 0:
                    col_count = 1
                target_col = min(max(target_col, 1), col_count)
                for row in rows:
                    cells = row.xpath('./th|./td')
                    if not cells:
                        new_cell = etree.Element('td')
                        new_cell.text = ''
                        row.append(new_cell)
                        continue
                    row_col_count = self._row_visual_col_count(row)
                    col_for_row = min(max(target_col, 1), max(row_col_count, 1))
                    loc = self._locate_cell_by_visual_col(cells, col_for_row)
                    anchor_cell = loc['cell']
                    if anchor_cell is None:
                        new_cell = etree.Element('td')
                        new_cell.text = ''
                        row.append(new_cell)
                        continue
                    if loc['span'] > 1 and col_for_row < loc['end']:
                        self._set_colspan(anchor_cell, loc['span'] + 1)
                    else:
                        new_cell = self._clone_cell_like(anchor_cell)
                        row.insert(loc['index'] + 1, new_cell)

        elif table_action == 'remove_col':
            if is_soce:
                self._apply_soce_remove_column(table, target_col)
            elif col_count > 1:
                target_col = min(max(target_col, 1), col_count)
                for row in rows:
                    cells = row.xpath('./th|./td')
                    row_col_count = self._row_visual_col_count(row)
                    if row_col_count <= 1:
                        continue
                    col_for_row = min(max(target_col, 1), row_col_count)
                    loc = self._locate_cell_by_visual_col(cells, col_for_row)
                    target_cell = loc['cell']
                    if target_cell is None:
                        continue
                    if loc['span'] > 1:
                        self._set_colspan(target_cell, loc['span'] - 1)
                    elif len(cells) > 1:
                        row.remove(target_cell)

        rendered_html = etree.tostring(root, encoding='unicode', method='html')
        return self._sanitize_html_for_storage(rendered_html)

    @api.model
    def _sanitize_html_for_storage(self, html_content):
        root = self._parse_html(html_content)
        root = self._normalize_document_root(root)
        root = self._sanitize_root(root)
        return self._serialize_document_html(root)

    def create_next_revision(self, html_content):
        self.ensure_one()
        self._ensure_active_company()
        sanitized_html = self._sanitize_html_for_storage(html_content)
        return self.document_id.create_revision_from_html(
            sanitized_html,
            parent_revision=self,
            tb_overrides_json=self.tb_overrides_json,
            lor_extra_items_json=self.lor_extra_items_json,
            wizard_snapshot_json=self.wizard_snapshot_json,
        )

    def _sync_document_snapshot_state(self):
        self.ensure_one()
        if self.document_id.current_revision_id != self:
            return

        write_vals = {}
        if (self.document_id.source_wizard_json or '') != (self.wizard_snapshot_json or ''):
            write_vals['source_wizard_json'] = self.wizard_snapshot_json or ''
        if (self.document_id.tb_overrides_json or '') != (self.tb_overrides_json or ''):
            write_vals['tb_overrides_json'] = self.tb_overrides_json or ''
        if (self.document_id.lor_extra_items_json or '') != (self.lor_extra_items_json or ''):
            write_vals['lor_extra_items_json'] = self.lor_extra_items_json or ''
        if write_vals:
            self.document_id.write(write_vals)

    def persist_session_revision_changes(
        self,
        html_content,
        tb_overrides_json='',
        lor_extra_items_json='',
        wizard_snapshot_json='',
        force_new_revision=False,
    ):
        self.ensure_one()
        self._ensure_active_company()

        prepared_html = html_content or ''
        tb_payload = tb_overrides_json or ''
        lor_payload = lor_extra_items_json or ''
        snapshot_payload = wizard_snapshot_json or ''

        has_changes = any([
            (self.html_content or '') != prepared_html,
            (self.tb_overrides_json or '') != tb_payload,
            (self.lor_extra_items_json or '') != lor_payload,
            (self.wizard_snapshot_json or '') != snapshot_payload,
        ])
        if not has_changes:
            return self, 'unchanged'

        if force_new_revision:
            return self.document_id.create_revision_from_html(
                prepared_html,
                parent_revision=self,
                tb_overrides_json=tb_payload,
                lor_extra_items_json=lor_payload,
                wizard_snapshot_json=snapshot_payload,
            ), 'new'

        if self.parent_revision_id:
            self.write({
                'html_content': prepared_html,
                'tb_overrides_json': tb_payload,
                'lor_extra_items_json': lor_payload,
                'wizard_snapshot_json': snapshot_payload,
            })
            if self.document_id.current_revision_id != self:
                self.document_id.current_revision_id = self.id
            self._sync_document_snapshot_state()
            return self, 'updated'

        return self.document_id.create_revision_from_html(
            prepared_html,
            parent_revision=self,
            tb_overrides_json=tb_payload,
            lor_extra_items_json=lor_payload,
            wizard_snapshot_json=snapshot_payload,
        ), 'new'

    def _compute_html_hash(self, html_content=None):
        self.ensure_one()
        source_html = self.html_content if html_content is None else html_content
        return hashlib.sha256((source_html or '').encode('utf-8')).hexdigest()

    def _get_pdf_content(self, pre_rendered_html=None, refresh_toc=True):
        self.ensure_one()
        self._ensure_active_company()

        html_started = time.perf_counter()
        if pre_rendered_html is None:
            render_ready_html = self._build_render_ready_html(refresh_toc=refresh_toc)
        else:
            render_ready_html = pre_rendered_html or ''
        _logger.debug(
            "AUDIT_PERF revision_pdf revision_id=%s stage=html elapsed_ms=%.2f",
            self.id,
            (time.perf_counter() - html_started) * 1000.0,
        )
        html_hash = self._compute_html_hash(render_ready_html)
        if self.pdf_attachment_id and self.pdf_hash == html_hash:
            datas = self.pdf_attachment_id.datas
            if datas:
                _logger.debug(
                    "AUDIT_PERF revision_pdf revision_id=%s stage=cache_hit",
                    self.id,
                )
                return base64.b64decode(datas)

        module_path = self._module_root_path()
        from ..controllers.main import AuditReportController

        controller = AuditReportController()
        pdf_started = time.perf_counter()
        pdf_content = controller._html_to_pdf(render_ready_html, base_url=module_path)
        _logger.debug(
            "AUDIT_PERF revision_pdf revision_id=%s stage=pdf elapsed_ms=%.2f",
            self.id,
            (time.perf_counter() - pdf_started) * 1000.0,
        )
        datas = base64.b64encode(pdf_content)

        filename = f"Audit_Report_{self.document_id.id}_v{self.version_no}.pdf"
        attachment_vals = {
            'name': filename,
            'datas': datas,
            'res_model': 'audit.report.revision',
            'res_id': self.id,
            'mimetype': 'application/pdf',
            'type': 'binary',
            'company_id': self.company_id.id,
        }

        attachment = self.pdf_attachment_id.sudo()
        if attachment:
            attachment.write(attachment_vals)
        else:
            attachment = self.env['ir.attachment'].sudo().create(attachment_vals)

        self.write({
            'pdf_attachment_id': attachment.id,
            'pdf_hash': html_hash,
            'pdf_generated_on': fields.Datetime.now(),
        })
        return pdf_content


class AuditReportPrintWizard(models.TransientModel):
    _name = 'audit.report.print.wizard'
    _description = 'Print Saved Audit Report Revision'

    company_id = fields.Many2one(
        'res.company',
        required=True,
        default=lambda self: self.env.company,
        readonly=True,
    )
    document_id = fields.Many2one(
        'audit.report.document',
        required=True,
        domain="[('company_id', '=', company_id)]",
    )
    revision_id = fields.Many2one(
        'audit.report.revision',
        required=True,
        domain="[('company_id', '=', company_id), ('document_id', '=', document_id), ('is_removed', '=', False)]",
    )

    @api.model
    def default_get(self, fields_list):
        values = super().default_get(fields_list)
        document_id = values.get('document_id') or self.env.context.get('default_document_id')
        if document_id:
            document = self.env['audit.report.document'].browse(document_id)
            if document and document.company_id == self.env.company and document.current_revision_id:
                values.setdefault('revision_id', document.current_revision_id.id)
        return values

    @api.onchange('document_id')
    def _onchange_document_id(self):
        if not self.document_id:
            self.revision_id = False
            return
        user_company_ids = self.env.user.company_ids.ids
        if self.document_id.company_id.id not in user_company_ids:
            self.document_id = False
            self.revision_id = False
            return
        current = self.document_id.current_revision_id
        self.revision_id = current if current and not current.is_removed else False

    def action_print_revision(self):
        self.ensure_one()
        user_company_ids = self.env.user.company_ids.ids
        if self.document_id.company_id.id not in user_company_ids:
            raise ValidationError(_('You can only print reports from companies allowed for your user.'))
        if self.revision_id.company_id.id not in user_company_ids:
            raise ValidationError(_('You can only print revisions from companies allowed for your user.'))
        if self.revision_id.is_removed:
            raise ValidationError(_('Removed revisions cannot be printed. Please restore the revision first.'))
        return {
            'type': 'ir.actions.act_url',
            'url': f'/audit_report/revision/{self.revision_id.id}/pdf',
            'target': 'new',
        }



class AuditReportDocumentExtension(models.Model):
    _inherit = 'audit.report.document'

    def _refresh_current_revision(self):
        for document in self:
            candidates = document.revision_ids.filtered(lambda rev: not rev.is_removed).sorted(
                key=lambda rev: (rev.version_no, rev.id),
                reverse=True,
            )
            document.current_revision_id = candidates[0].id if candidates else False
