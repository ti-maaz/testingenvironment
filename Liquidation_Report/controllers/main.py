import html as html_lib
import logging
import os
import re
import xml.etree.ElementTree as ET
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

from odoo import fields, http
from odoo.exceptions import ValidationError
from odoo.http import request


_logger = logging.getLogger(__name__)

W_NS = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
XML_NS = 'http://www.w3.org/XML/1998/namespace'
NS = {'w': W_NS}

ET.register_namespace('w', W_NS)
ET.register_namespace('r', 'http://schemas.openxmlformats.org/officeDocument/2006/relationships')
ET.register_namespace('wp', 'http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing')
ET.register_namespace('a', 'http://schemas.openxmlformats.org/drawingml/2006/main')
ET.register_namespace('pic', 'http://schemas.openxmlformats.org/drawingml/2006/picture')
ET.register_namespace('mc', 'http://schemas.openxmlformats.org/markup-compatibility/2006')
ET.register_namespace('m', 'http://schemas.openxmlformats.org/officeDocument/2006/math')
ET.register_namespace('v', 'urn:schemas-microsoft-com:vml')
ET.register_namespace('o', 'urn:schemas-microsoft-com:office:office')
ET.register_namespace('w10', 'urn:schemas-microsoft-com:office:word')
ET.register_namespace('w14', 'http://schemas.microsoft.com/office/word/2010/wordml')
ET.register_namespace('w15', 'http://schemas.microsoft.com/office/word/2012/wordml')


class LiquidationReportController(http.Controller):
    IFZA_TEMPLATE_FILENAME = 'IFZA Liquidation Report.docx'
    ALL_FREEZONES_TEMPLATE_FILENAME = 'Liquidation Letter - all free zones except IFZA and Meydan.docx'

    @staticmethod
    def _template_path(filename):
        module_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        return os.path.join(module_dir, 'templates', filename)

    @staticmethod
    def _get_liquidation_company(record):
        company = getattr(record, 'company_id', False)
        if company and company.exists():
            return company
        return record.env.company

    @staticmethod
    def _plain_date(date_value):
        date_value = fields.Date.to_date(date_value) if date_value else False
        if not date_value:
            return ''
        return f"{date_value.day} {date_value.strftime('%B %Y')}"

    @classmethod
    def _ordinal_date(cls, date_value):
        date_value = fields.Date.to_date(date_value) if date_value else False
        if not date_value:
            return ''
        day = date_value.day
        if 10 <= day % 100 <= 20:
            suffix = 'th'
        else:
            suffix = {1: 'st', 2: 'nd', 3: 'rd'}.get(day % 10, 'th')
        return f"{day}{suffix} {date_value.strftime('%B %Y')}"

    @staticmethod
    def _clean_text(value):
        return ' '.join(str(value or '').split())

    @staticmethod
    def _company_name_for_doc(record):
        return LiquidationReportController._clean_text(
            getattr(record, 'company_name', False)
            or getattr(record.company_id, 'name', False)
        ).upper()

    @staticmethod
    def _free_zone_label(record):
        company = LiquidationReportController._get_liquidation_company(record)
        free_zone_value = (
            getattr(record, 'company_free_zone', False)
            or getattr(company, 'free_zone', False)
            or ''
        )
        selection = dict(company._fields['free_zone'].selection or [])
        return LiquidationReportController._clean_text(
            selection.get(free_zone_value, free_zone_value)
        )

    @classmethod
    def _free_zone_to_line(cls, record):
        authority = cls._free_zone_label(record)
        city = cls._clean_text(
            getattr(record, 'company_city', False)
            or getattr(record.company_id, 'city', False)
        )
        if authority and city and not authority.lower().endswith(city.lower()):
            return f'{authority}, {city}'
        return authority or city

    @classmethod
    def _company_address_for_doc(cls, record):
        parts = []
        for value in (
            getattr(record, 'company_street', False),
            getattr(record, 'company_street2', False),
            getattr(record, 'company_city', False),
        ):
            cleaned = cls._clean_text(value)
            if cleaned and cleaned not in parts:
                parts.append(cleaned)
        return ', '.join(parts)

    @classmethod
    def _build_placeholder_values(cls, record):
        return {
            'company_name': cls._company_name_for_doc(record),
            'license_number': cls._clean_text(getattr(record, 'company_license_number', False)),
            'liquidation_date': cls._ordinal_date(getattr(record, 'liquidation_date', False)),
            'letter_date': cls._plain_date(getattr(record, 'letter_date', False)),
            'contact_person': cls._clean_text(getattr(record, 'contact_person', False)),
            'company_address': cls._company_address_for_doc(record),
            'free_zone_authority': cls._free_zone_label(record),
            'free_zone_to_line': cls._free_zone_to_line(record),
        }

    @staticmethod
    def _run_text(run):
        return ''.join(text_node.text or '' for text_node in run.findall('.//w:t', NS))

    @staticmethod
    def _paragraph_text(paragraph):
        return ''.join(text_node.text or '' for text_node in paragraph.findall('.//w:t', NS))

    @staticmethod
    def _run_has_highlight(run):
        return run.find('w:rPr/w:highlight', NS) is not None

    @staticmethod
    def _remove_run_highlights(run):
        run_properties = run.find('w:rPr', NS)
        if run_properties is None:
            return
        for highlight in list(run_properties.findall('w:highlight', NS)):
            run_properties.remove(highlight)

    @staticmethod
    def _strip_all_highlights(root):
        """Remove every w:highlight element anywhere in the tree.

        Per-run removal misses highlights carried by the paragraph-mark run
        properties (w:pPr/w:rPr/w:highlight), so sweep the whole document to
        guarantee no yellow placeholder shading survives.
        """
        highlight_tag = f'{{{W_NS}}}highlight'
        for parent in root.iter():
            for child in list(parent):
                if child.tag == highlight_tag:
                    parent.remove(child)

    @staticmethod
    def _set_text_node_value(text_node, value):
        value = str(value or '')
        if value and (value[:1].isspace() or value[-1:].isspace()):
            text_node.set(f'{{{XML_NS}}}space', 'preserve')
        else:
            text_node.attrib.pop(f'{{{XML_NS}}}space', None)
        text_node.text = value

    @classmethod
    def _set_run_text(cls, run, value):
        text_nodes = run.findall('.//w:t', NS)
        if not text_nodes:
            text_node = ET.SubElement(run, f'{{{W_NS}}}t')
            text_nodes = [text_node]
        cls._set_text_node_value(text_nodes[0], value)
        for text_node in text_nodes[1:]:
            cls._set_text_node_value(text_node, '')

    @classmethod
    def _set_highlight_group_text(cls, group, value):
        if not group:
            return
        cls._set_run_text(group[0], value)
        for run in group[1:]:
            cls._set_run_text(run, '')

    @classmethod
    def _highlight_groups(cls, paragraph):
        groups = []
        current_group = []
        for run in paragraph.findall('.//w:r', NS):
            if cls._run_has_highlight(run):
                current_group.append(run)
                continue
            if current_group and cls._run_text(run):
                groups.append(current_group)
                current_group = []
        if current_group:
            groups.append(current_group)
        return groups

    @classmethod
    def _replace_highlight_groups(cls, paragraph, replacements):
        groups = cls._highlight_groups(paragraph)
        for index, group in enumerate(groups):
            if index < len(replacements) and replacements[index] is not None:
                cls._set_highlight_group_text(group, replacements[index])
            for run in group:
                cls._remove_run_highlights(run)

    @classmethod
    def _replace_text_in_paragraph(cls, paragraph, old_text, new_text):
        if not old_text:
            return
        for text_node in paragraph.findall('.//w:t', NS):
            if text_node.text and old_text in text_node.text:
                cls._set_text_node_value(
                    text_node,
                    text_node.text.replace(old_text, new_text),
                )

    @classmethod
    def _apply_ifza_paragraph_replacements(cls, paragraph, values):
        text = cls._paragraph_text(paragraph)
        replacements = []
        if not cls._highlight_groups(paragraph):
            return

        if text.strip().startswith('ADC VENTURES') and text.strip().endswith('FZCO'):
            replacements = [values['company_name']]
        elif 'License number' in text:
            replacements = [
                f"{values['company_name']} ",
                values['license_number'],
                values['liquidation_date'],
            ]
        elif 'Liquidated Statement of Affairs' in text:
            replacements = [
                values['company_name'],
                f" {values['liquidation_date']}",
            ]
        elif 'Name of contact person' in text:
            if values.get('company_address'):
                cls._replace_text_in_paragraph(
                    paragraph,
                    'DSO-IFZA, IFZA Properties, Dubai Silicon Oasis, Dubai;',
                    f"{values['company_address']};",
                )
            replacements = [values['contact_person']]
        elif 'statement of financial position' in text:
            replacements = [
                values['company_name'],
                f" {values['liquidation_date']}",
            ]
        cls._replace_highlight_groups(paragraph, replacements)

    @classmethod
    def _apply_all_freezones_paragraph_replacements(cls, paragraph, values):
        text = cls._paragraph_text(paragraph)
        stripped_text = text.strip()
        replacements = []
        if not cls._highlight_groups(paragraph):
            return

        if stripped_text.startswith('Date:'):
            replacements = [values['letter_date']]
        elif stripped_text.startswith('Ref:'):
            replacements = []
        elif stripped_text.startswith('To:'):
            replacements = [values['free_zone_to_line']]
        elif stripped_text.startswith('For:'):
            replacements = [values['company_name']]
        elif stripped_text.endswith(', UAE.') and len(cls._highlight_groups(paragraph)) == 1:
            replacements = [values['company_address']]
        elif 'bearing license No.' in text:
            replacements = [
                f"{values['company_name']} ",
                values['license_number'],
            ]
        elif 'liquidation expenses are being paid' in text:
            replacements = [f"{values['company_name']} "]
        elif 'creditors of' in text:
            replacements = [f"{values['company_name']} "]
        elif 'further claims against' in text:
            replacements = [values['company_name']]
        elif 'application to the' in text:
            replacements = [f"{values['free_zone_authority']} "]
        cls._replace_highlight_groups(paragraph, replacements)

    @classmethod
    def _fill_document_xml(cls, xml_content, report_type, values):
        root = ET.fromstring(xml_content)
        for paragraph in root.findall('.//w:p', NS):
            if report_type == 'ifza':
                cls._apply_ifza_paragraph_replacements(paragraph, values)
            else:
                cls._apply_all_freezones_paragraph_replacements(paragraph, values)
        cls._strip_all_highlights(root)
        return ET.tostring(root, encoding='utf-8', xml_declaration=True)

    @classmethod
    def _template_filename_for_report_type(cls, report_type):
        if report_type == 'ifza':
            return cls.IFZA_TEMPLATE_FILENAME
        return cls.ALL_FREEZONES_TEMPLATE_FILENAME

    def _build_liquidation_docx(self, record):
        record._validate_liquidation_settings()
        report_type = record.report_type or 'all_freezones'
        values = self._build_placeholder_values(record)
        template_path = self._template_path(self._template_filename_for_report_type(report_type))

        output_buffer = BytesIO()
        with ZipFile(template_path, mode='r') as source_archive:
            with ZipFile(output_buffer, mode='w', compression=ZIP_DEFLATED) as output_archive:
                for entry in source_archive.infolist():
                    content = source_archive.read(entry.filename)
                    if entry.filename == 'word/document.xml':
                        content = self._fill_document_xml(content, report_type, values)
                    output_archive.writestr(entry, content)
        return output_buffer.getvalue()

    @staticmethod
    def _build_liquidation_filename(record):
        company_name = (getattr(record.company_id, 'name', '') or '').strip()
        safe_company_name = re.sub(r'[^A-Za-z0-9]+', '_', company_name).strip('_')
        if not safe_company_name:
            safe_company_name = f'company_{record.id}'
        report_type = 'IFZA' if record.report_type == 'ifza' else 'All_Freezones'
        return f'Liquidation_Report_{report_type}_{safe_company_name}.docx'

    @staticmethod
    def _render_html_response(title, body_html, status=200):
        safe_title = html_lib.escape(title or 'Liquidation Report')
        page = f"""<!doctype html>
<html>
  <head>
    <meta charset="utf-8"/>
    <title>{safe_title}</title>
  </head>
  <body>{body_html}</body>
</html>"""
        return request.make_response(
            page,
            headers=[('Content-Type', 'text/html; charset=utf-8')],
            status=status,
        )

    @staticmethod
    def _forbidden_response(message='Forbidden'):
        return request.make_response(
            message,
            headers=[('Content-Type', 'text/plain; charset=utf-8')],
            status=403,
        )

    def _generate_liquidation_docx_response(self, record):
        company = self._get_liquidation_company(record)
        if company.id not in request.env.user.company_ids.ids:
            return self._forbidden_response(
                "This liquidation report belongs to a company not allowed for your user."
            )

        try:
            docx_content = self._build_liquidation_docx(record)
        except (ValidationError, OSError) as error:
            _logger.exception("Liquidation report DOCX generation failed: %s", error)
            safe_error = html_lib.escape(str(error) or 'Unable to generate the liquidation report.')
            return self._render_html_response(
                'Liquidation Report Error',
                f'<h1>Liquidation Report Error</h1><p>{safe_error}</p>',
                status=500,
            )
        except Exception as error:
            _logger.exception("Liquidation report DOCX generation failed: %s", error)
            return self._render_html_response(
                'Liquidation Report Error',
                '<h1>Liquidation Report Error</h1><p>Unable to generate the liquidation report.</p>',
                status=500,
            )

        filename = self._build_liquidation_filename(record)
        return request.make_response(
            docx_content,
            headers=[
                (
                    'Content-Type',
                    'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                ),
                ('Content-Disposition', f'attachment; filename="{filename}"'),
                ('Content-Length', str(len(docx_content))),
                ('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0'),
                ('Pragma', 'no-cache'),
                ('Expires', '0'),
            ],
        )

    @http.route('/liquidation_report/docx/<int:wizard_id>', type='http', auth='user')
    def generate_liquidation_docx(self, wizard_id, **kwargs):
        wizard = request.env['liquidation.report.wizard'].browse(wizard_id)
        if not wizard.exists():
            return request.not_found()
        return self._generate_liquidation_docx_response(wizard)
