import html as html_lib
import logging
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from functools import lru_cache
from io import BytesIO
from zipfile import ZIP_DEFLATED, ZipFile

from dateutil.relativedelta import relativedelta
from jinja2 import Environment

from odoo import fields, http
from odoo.exceptions import ValidationError
from odoo.http import request

from ..models.res_company import get_default_lor_css_source
from ..models.res_company import get_default_lor_html_source

_logger = logging.getLogger(__name__)
LOR_LINE_BREAK_TOKEN = '[[LOR_LINE_BREAK]]'
LOR_GAP_AFTER_TWIPS = 240


@lru_cache(maxsize=1)
def _get_lor_template_env():
    return Environment()


class LorReportController(http.Controller):
    @staticmethod
    def _get_lor_company(record):
        company = getattr(record, 'company_id', False)
        if company and company.exists():
            return company
        return record.env.company

    def _get_lor_template_content_for_company(self, company):
        return get_default_lor_html_source()

    def _get_lor_css_content_for_company(self, company):
        if hasattr(company, '_get_lor_template_css_source'):
            return company._get_lor_template_css_source()
        return get_default_lor_css_source()

    @staticmethod
    def _join_lor_names(names):
        normalized_names = [str(name or '').strip() for name in names if str(name or '').strip()]
        if not normalized_names:
            return ''
        if len(normalized_names) == 1:
            return normalized_names[0]
        if len(normalized_names) == 2:
            return f'{normalized_names[0]} and {normalized_names[1]}'
        return f"{', '.join(normalized_names[:-1])} and {normalized_names[-1]}"

    @staticmethod
    def _get_lor_signature_manager_names(source):
        if not source:
            return [], False

        manager_names = []
        has_signature_flags = False
        for index in range(1, 11):
            include_field_name = f'signature_include_{index}'
            if hasattr(source, include_field_name):
                has_signature_flags = True
                if not getattr(source, include_field_name, False):
                    continue
            manager_name = (getattr(source, f'shareholder_{index}', '') or '').strip()
            if manager_name:
                manager_names.append(manager_name)
        return manager_names, has_signature_flags

    @staticmethod
    def _get_lor_manager_name(record):
        if hasattr(record, '_get_lor_manager_names'):
            manager_names = record._get_lor_manager_names()
            if manager_names:
                return manager_names
            _signature_names, has_signature_flags = LorReportController._get_lor_signature_manager_names(record)
            if has_signature_flags:
                return ''

        company = getattr(record, 'company_id', False)
        saw_signature_flags = False
        for source in (record, company):
            if not source:
                continue
            manager_names, has_signature_flags = LorReportController._get_lor_signature_manager_names(source)
            saw_signature_flags = saw_signature_flags or has_signature_flags
            if has_signature_flags and not manager_names:
                continue
            if not has_signature_flags:
                manager_names = []
                for index in range(1, 11):
                    manager_name = (getattr(source, f'shareholder_{index}', '') or '').strip()
                    if manager_name:
                        manager_names.append(manager_name)
            joined_names = LorReportController._join_lor_names(manager_names)
            if joined_names:
                return joined_names
        if saw_signature_flags:
            return ''
        return (getattr(record.env.user, 'name', '') or '').strip()

    @staticmethod
    def _get_lor_signature_date(record):
        signature_date_mode = (getattr(record, 'signature_date_mode', '') or 'today').strip().lower()
        if signature_date_mode == 'manual' and getattr(record, 'signature_manual_date', False):
            return fields.Date.to_date(record.signature_manual_date)
        if signature_date_mode == 'report_end' and getattr(record, 'date_end', False):
            return fields.Date.to_date(record.date_end)
        return fields.Date.context_today(record)

    @staticmethod
    def _get_lor_period_word(record):
        start_date = fields.Date.to_date(record.date_start) if getattr(record, 'date_start', False) else False
        end_date = fields.Date.to_date(record.date_end) if getattr(record, 'date_end', False) else False
        if not start_date or not end_date:
            return 'year'
        expected_year_end = start_date + relativedelta(years=1) - relativedelta(days=1)
        return 'year' if expected_year_end == end_date else 'period'

    def _build_lor_placeholder_values(self, record):
        signature_date = self._get_lor_signature_date(record)
        end_date = fields.Date.to_date(record.date_end) if getattr(record, 'date_end', False) else False
        period_word = self._get_lor_period_word(record)
        company = self._get_lor_company(record)
        company_city = (
            getattr(record, 'company_city', False)
            or getattr(company, 'city', False)
            or ''
        )
        free_zone_value = (
            getattr(record, 'company_free_zone', False)
            or getattr(company, 'free_zone', False)
            or ''
        )
        free_zone_selection = dict(company._fields['free_zone'].selection or [])
        free_zone_city = free_zone_selection.get(free_zone_value, free_zone_value)

        return {
            'COMPANYNAME': (company.name or '').strip(),
            'FREEZONECITY': (free_zone_city or '').strip(),
            'CITY': (company_city or '').strip(),
            'ENDDATE': end_date.strftime('%d %B %Y') if end_date else '',
            'PERIODWORD': period_word,
            'MANAGER': self._get_lor_manager_name(record),
            'DATE': signature_date.strftime('%d/%m/%Y') if signature_date else '',
        }

    @staticmethod
    def _replace_lor_placeholders(template_text, placeholder_values):
        if not template_text:
            return ''

        values = placeholder_values or {}
        placeholder_pattern = re.compile(r'<<\s*([^<>]+?)\s*>>')

        def _replace(match):
            normalized_key = re.sub(r'\s+', '', match.group(1) or '').upper()
            value = values.get(normalized_key)
            if value is None:
                return match.group(0)
            return str(value)

        return placeholder_pattern.sub(_replace, template_text)

    def _render_lor_template_content_from_source(
        self,
        template_text,
        placeholder_values,
        extra_main_items=None,
    ):
        values = placeholder_values or {}
        context = {
            'company_name': values.get('COMPANYNAME', ''),
            'free_zone_city': values.get('FREEZONECITY', ''),
            'city': values.get('CITY', ''),
            'end_date': values.get('ENDDATE', ''),
            'period_word': values.get('PERIODWORD', 'year'),
            'manager_name': values.get('MANAGER', ''),
            'signature_date': values.get('DATE', ''),
            'placeholders': values,
        }

        source_text = template_text or ''
        rendered = source_text
        try:
            template = _get_lor_template_env().from_string(source_text)
            rendered = template.render(**context)
        except Exception:
            rendered = source_text

        resolved_content = self._replace_lor_placeholders(rendered, values)
        return self._inject_lor_extra_main_items(
            resolved_content,
            extra_main_items=extra_main_items,
        )

    @staticmethod
    def _normalize_lor_extra_items(extra_items):
        normalized = []
        for item in extra_items or []:
            item_text = str(item or '').strip()
            if item_text:
                normalized.append(item_text)
        return normalized

    def _inject_lor_extra_main_items(
        self,
        rendered_lor_html,
        extra_items=None,
        extra_main_items=None,
    ):
        item_source = extra_items if extra_items is not None else extra_main_items
        item_texts = self._normalize_lor_extra_items(item_source)
        if not item_texts:
            return rendered_lor_html or ''

        raw_html = (rendered_lor_html or '').strip()
        if not raw_html:
            return rendered_lor_html or ''

        try:
            root = ET.fromstring(raw_html)
        except ET.ParseError:
            return rendered_lor_html or ''

        target_list = None
        for node in root.iter():
            if self._xml_tag_name(node) != 'ol':
                continue
            class_tokens = self._node_class_tokens(node)
            if 'list-level-0' in class_tokens:
                target_list = node
                break
            if target_list is None:
                target_list = node

        if target_list is None:
            return rendered_lor_html or ''

        for item_text in item_texts:
            li_node = ET.Element('li')
            li_node.text = item_text
            target_list.append(li_node)

        return ET.tostring(root, encoding='unicode')

    @staticmethod
    def _xml_tag_name(node):
        raw_tag = getattr(node, 'tag', '') or ''
        if '}' in raw_tag:
            return raw_tag.split('}', 1)[1].lower()
        return raw_tag.lower()

    @staticmethod
    def _node_class_tokens(node):
        class_attr = ((getattr(node, 'attrib', {}) or {}).get('class') or '').strip()
        if not class_attr:
            return set()
        return {token.strip().lower() for token in class_attr.split() if token.strip()}

    def _collect_lor_inline_runs(self, node, inherited_bold=False, skip_nested_lists=False):
        runs = []
        node_tag = self._xml_tag_name(node)
        is_bold = inherited_bold or node_tag in ('b', 'strong')

        if getattr(node, 'text', None):
            runs.append((node.text, is_bold))

        for child in list(node):
            child_tag = self._xml_tag_name(child)
            if skip_nested_lists and child_tag in ('ol', 'ul'):
                if getattr(child, 'tail', None):
                    runs.append((child.tail, is_bold))
                continue
            if child_tag == 'br':
                runs.append((LOR_LINE_BREAK_TOKEN, is_bold))
                if getattr(child, 'tail', None):
                    runs.append((child.tail, is_bold))
                continue

            runs.extend(
                self._collect_lor_inline_runs(
                    child,
                    inherited_bold=is_bold,
                    skip_nested_lists=False,
                )
            )
            if getattr(child, 'tail', None):
                runs.append((child.tail, is_bold))

        return runs

    @staticmethod
    def _runs_to_markdown_text(runs):
        chunks = []
        for text_value, is_bold in runs or []:
            if text_value is None:
                continue
            if text_value == LOR_LINE_BREAK_TOKEN:
                while chunks and chunks[-1].endswith(' '):
                    chunks[-1] = chunks[-1].rstrip()
                    if chunks[-1]:
                        break
                    chunks.pop()
                chunks.append(LOR_LINE_BREAK_TOKEN)
                continue
            normalized = text_value.replace('\n', ' ').replace('\t', ' ')
            normalized = re.sub(r'\s+', ' ', normalized)
            if not normalized.strip():
                if chunks and not chunks[-1].endswith(' '):
                    chunks.append(' ')
                continue
            if is_bold:
                chunks.append(f'**{normalized}**')
            else:
                chunks.append(normalized)

        output = ''.join(chunks)
        output = re.sub(r'\s+([,.;:!?])', r'\1', output)
        output = re.sub(r'\(\s+', '(', output)
        output = re.sub(r'\s+\)', ')', output)
        return output.strip()

    def _append_lor_list_blocks(self, list_node, blocks, level=0):
        list_kind = 'unordered' if self._xml_tag_name(list_node) == 'ul' else 'ordered'
        list_class_tokens = self._node_class_tokens(list_node)
        list_items = [
            child for child in list(list_node)
            if self._xml_tag_name(child) == 'li'
        ]
        last_index = len(list_items) - 1
        for item_index, child in enumerate(list_items):
            is_last_item = item_index == last_index

            line_text = self._runs_to_markdown_text(
                self._collect_lor_inline_runs(child, skip_nested_lists=True)
            )
            effective_level = int(level) if level is not None else 0
            style_key = 'list_item_level_0'
            item_class_tokens = self._node_class_tokens(child)
            if effective_level > 0:
                style_key = 'list_item_level_1_last' if is_last_item else 'list_item_level_1'
            gap_after_twips = 0
            if effective_level == 0 and (
                'gap' in item_class_tokens or 'gap' in list_class_tokens
            ):
                gap_after_twips = LOR_GAP_AFTER_TWIPS
            elif effective_level > 0 and is_last_item:
                gap_after_twips = LOR_GAP_AFTER_TWIPS
            blocks.append({
                'text': line_text,
                'title_style': False,
                'list_level': effective_level,
                'list_kind': list_kind,
                'style_key': style_key,
                'gap_after_twips': gap_after_twips,
                'preserve_empty': False,
            })

            for nested in list(child):
                nested_tag = self._xml_tag_name(nested)
                if nested_tag in ('ol', 'ul'):
                    self._append_lor_list_blocks(nested, blocks, level=level + 1)

    def _extract_lor_blocks_from_html(self, html_content):
        wrapped_html = (html_content or '').strip()
        if not wrapped_html:
            return []

        try:
            root = ET.fromstring(wrapped_html)
        except ET.ParseError:
            root = ET.fromstring(f'<root>{wrapped_html}</root>')

        blocks = []
        class_style_map = (
            ('address-line', 'address_line'),
            ('salutation', 'salutation'),
            ('intro', 'intro'),
            ('closing', 'closing'),
            ('signature-line', 'signature_line'),
            ('date-line', 'date_line'),
            ('spacer-line', 'spacer_line'),
            ('spacer-lg', 'spacer_lg'),
            ('spacer-sm', 'spacer_sm'),
            ('paragraph', 'paragraph'),
        )

        def walk(node):
            for child in list(node):
                tag = self._xml_tag_name(child)
                if tag in ('h1', 'h2'):
                    text = self._runs_to_markdown_text(self._collect_lor_inline_runs(child))
                    blocks.append({
                        'text': text,
                        'title_style': True,
                        'list_level': None,
                        'list_kind': None,
                        'style_key': 'title',
                        'preserve_empty': False,
                    })
                    continue
                if tag == 'p':
                    text = self._runs_to_markdown_text(self._collect_lor_inline_runs(child))
                    style_key = 'paragraph'
                    class_tokens = self._node_class_tokens(child)
                    for class_name, mapped_style in class_style_map:
                        if class_name in class_tokens:
                            style_key = mapped_style
                            break
                    preserve_empty = style_key in ('spacer_line', 'spacer_lg', 'spacer_sm') and not text
                    blocks.append({
                        'text': text,
                        'title_style': False,
                        'list_level': None,
                        'list_kind': None,
                        'style_key': style_key,
                        'gap_after_twips': LOR_GAP_AFTER_TWIPS if 'gap' in class_tokens else 0,
                        'preserve_empty': preserve_empty,
                    })
                    continue
                if tag == 'br':
                    blocks.append({
                        'text': '',
                        'title_style': False,
                        'list_level': None,
                        'list_kind': None,
                        'style_key': 'spacer_line',
                        'gap_after_twips': 0,
                        'preserve_empty': True,
                    })
                    continue
                if tag in ('ol', 'ul'):
                    self._append_lor_list_blocks(child, blocks, level=0)
                    continue
                walk(child)

        walk(root)
        return blocks

    def _extract_lor_blocks_from_text(self, body_text):
        lines = (body_text or '').split('\n')
        if not lines:
            return []

        blocks = []
        for line in lines:
            is_main_title = line.strip().upper() == 'AUDIT REPRESENTATION LETTER'
            top_level_match = re.match(r'^\s*\d+\.\s+(.*)$', line)
            sub_level_match = re.match(r'^\s*[A-Za-z]\.\s+(.*)$', line)
            unordered_match = re.match(r'^\s*[-*•]\s+(.*)$', line)

            list_level = None
            list_kind = None
            line_content = line
            if top_level_match:
                list_level = 0
                list_kind = 'ordered'
                line_content = top_level_match.group(1)
            elif sub_level_match:
                list_level = 1
                list_kind = 'ordered'
                line_content = sub_level_match.group(1)
            elif unordered_match:
                list_level = 0
                list_kind = 'unordered'
                line_content = unordered_match.group(1)

            style_key = 'paragraph'
            if list_level == 0:
                style_key = 'list_item_level_0'
            elif list_level == 1:
                style_key = 'list_item_level_1'
            elif is_main_title:
                style_key = 'title'

            blocks.append({
                'text': line_content,
                'title_style': is_main_title,
                'list_level': list_level,
                'list_kind': list_kind,
                'style_key': style_key,
                'gap_after_twips': 0,
                'preserve_empty': False,
            })
        return blocks

    def _extract_lor_blocks(self, body_content):
        raw = (body_content or '').strip()
        is_structured_html = bool(re.search(r'<\s*(html|body|h1|p|ol|li)\b', raw, flags=re.IGNORECASE))
        if is_structured_html:
            try:
                return self._extract_lor_blocks_from_html(raw)
            except Exception:
                pass
        return self._extract_lor_blocks_from_text(body_content)

    @staticmethod
    def _default_lor_docx_styles():
        return {
            'document': {
                'page_width': 11906,
                'page_height': 16838,
                'page_orientation': 'portrait',
                'margin_top': 1928,
                'margin_right': 1440,
                'margin_bottom': 850,
                'margin_left': 1440,
                'header': 680,
                'footer': 113,
                'gutter': 0,
                'gutter_position': 'left',
                'column_space': 720,
                'line_pitch': 360,
                'default_header_text': 'ON COMPANY LETTERHEAD',
                'first_page_header_text': '',
                'header_font_family': 'Times New Roman',
                'header_font_size_half_points': 22,
                'header_bold': False,
                'header_text_align': 'center',
                'header_spacing_before': 0,
                'header_spacing_after': 120,
                'page_numbering': True,
                'page_number_align': 'center',
                'page_number_font_family': 'Times New Roman',
                'page_number_font_size_half_points': 18,
                'page_number_bold': False,
                'page_number_position_half_points': 0,
                'page_number_line_height': 180,
            },
            'body': {
                'font_family': 'Times New Roman',
                'font_size_half_points': 24,
                'bold': False,
                'line_height': 240,
            },
            'paragraph': {
                'text_align': 'left',
                'spacing_before': 0,
                'spacing_after': 0,
                'line_height': 240,
            },
            'address_line': {
                'text_align': 'left',
                'spacing_before': 0,
                'spacing_after': 0,
                'line_height': 240,
            },
            'salutation': {
                'text_align': 'left',
                'spacing_before': 0,
                'spacing_after': 0,
                'line_height': 240,
            },
            'intro': {
                'text_align': 'both',
                'spacing_before': 0,
                'spacing_after': 0,
                'line_height': 240,
            },
            'closing': {
                'text_align': 'left',
                'spacing_before': 0,
                'spacing_after': 0,
                'line_height': 240,
            },
            'signature_line': {
                'text_align': 'left',
                'spacing_before': 0,
                'spacing_after': 0,
                'line_height': 240,
            },
            'date_line': {
                'text_align': 'left',
                'spacing_before': 0,
                'spacing_after': 0,
                'line_height': 240,
            },
            'spacer_line': {
                'spacing_before': 0,
                'spacing_after': 0,
                'line_height': 240,
            },
            'spacer_sm': {
                'spacing_before': 0,
                'spacing_after': 0,
                'line_height': 240,
            },
            'spacer_lg': {
                'spacing_before': 0,
                'spacing_after': 0,
                'line_height': 240,
            },
            'list_item_level_0': {
                'text_align': 'left',
                'spacing_before': 0,
                'spacing_after': 0,
                'line_height': 240,
            },
            'list_item_level_1': {
                'text_align': 'left',
                'spacing_before': 0,
                'spacing_after': 0,
                'line_height': 240,
            },
            'list_item_level_1_last': {
                'text_align': 'left',
                'spacing_before': 0,
                'spacing_after': 240,
                'line_height': 240,
            },
            'title': {
                'font_family': 'Times New Roman',
                'font_size_half_points': 24,
                'bold': True,
                'text_align': 'center',
                'spacing_before': 0,
                'spacing_after': 0,
                'line_height': 240,
            },
            'list_level_0': {
                'indent_left': 720,
                'indent_hanging': 360,
                'restart': False,
            },
            'list_level_1': {
                'indent_left': 1440,
                'indent_hanging': 360,
                'restart': True,
            },
        }

    @staticmethod
    def _parse_css_length_to_twips(value, default):
        raw = (value or '').strip().lower()
        if not raw:
            return int(default)
        match = re.fullmatch(r'(-?\d+(?:\.\d+)?)([a-z]*)', raw)
        if not match:
            return int(default)
        number = float(match.group(1))
        unit = match.group(2) or 'pt'
        unit_factors = {
            'twip': 1.0,
            'twips': 1.0,
            'pt': 20.0,
            'px': 15.0,
            'in': 1440.0,
            'cm': 566.929,
            'mm': 56.6929,
        }
        factor = unit_factors.get(unit)
        if factor is None:
            return int(default)
        return int(round(number * factor))

    @staticmethod
    def _parse_css_length_to_half_points(value, default):
        raw = (value or '').strip().lower()
        if not raw:
            return int(default)
        match = re.fullmatch(r'(-?\d+(?:\.\d+)?)([a-z]*)', raw)
        if not match:
            return int(default)
        number = float(match.group(1))
        unit = match.group(2) or 'pt'
        if unit in ('', 'pt'):
            return int(round(number * 2.0))
        if unit == 'px':
            return int(round(number * 1.5))
        if unit in ('twip', 'twips'):
            return int(round(number / 10.0))
        return int(default)

    @staticmethod
    def _parse_css_bool(value, default=False):
        normalized = (value or '').strip().lower()
        if normalized in ('1', 'true', 'yes', 'on', 'bold'):
            return True
        if normalized in ('0', 'false', 'no', 'off', 'normal'):
            return False
        return bool(default)

    @staticmethod
    def _normalize_docx_alignment(value, default='left'):
        normalized = (value or '').strip().lower()
        if normalized in ('left', 'center', 'right', 'both'):
            return normalized
        if normalized == 'justify':
            return 'both'
        return default

    @staticmethod
    def _normalize_docx_orientation(value, default='portrait'):
        normalized = (value or '').strip().lower()
        if normalized in ('portrait', 'landscape'):
            return normalized
        return default

    @staticmethod
    def _parse_css_string(value, default=''):
        raw = (value or '').strip()
        if not raw:
            return default
        if (raw.startswith('"') and raw.endswith('"')) or (raw.startswith("'") and raw.endswith("'")):
            return raw[1:-1]
        return raw

    def _parse_lor_css_styles(self, css_text):
        style_map = {
            name: dict(values)
            for name, values in self._default_lor_docx_styles().items()
        }
        if not css_text:
            return style_map

        cleaned = re.sub(r'/\*.*?\*/', '', css_text, flags=re.DOTALL)
        selector_map = {
            'page': 'document',
            '@page': 'document',
            '.lor-page': 'document',
            'body': 'body',
            '.title': 'title',
            '.lor-title': 'title',
            'title': 'title',
            'p': 'paragraph',
            '.paragraph': 'paragraph',
            '.lor-paragraph': 'paragraph',
            '.address-line': 'address_line',
            '.salutation': 'salutation',
            '.intro': 'intro',
            '.closing': 'closing',
            '.signature-line': 'signature_line',
            '.date-line': 'date_line',
            '.spacer-line': 'spacer_line',
            '.spacer-sm': 'spacer_sm',
            '.spacer-lg': 'spacer_lg',
            '.list-level-0': 'list_level_0',
            'list-level-0': 'list_level_0',
            '.list-level-1': 'list_level_1',
            'list-level-1': 'list_level_1',
            '.list-item-0': 'list_item_level_0',
            '.list-item-1': 'list_item_level_1',
            '.list-item-1-last': 'list_item_level_1_last',
            '.list-level-0 li': 'list_item_level_0',
            '.list-level-1 li': 'list_item_level_1',
        }

        for selector_text, declarations in re.findall(r'([^{}]+)\{([^{}]*)\}', cleaned):
            selectors = [item.strip().lower() for item in selector_text.split(',') if item.strip()]
            if not selectors:
                continue
            mapped_targets = [selector_map.get(selector) for selector in selectors]
            mapped_targets = [target for target in mapped_targets if target]
            if not mapped_targets:
                continue

            properties = {}
            for declaration in declarations.split(';'):
                if ':' not in declaration:
                    continue
                key, value = declaration.split(':', 1)
                prop_name = key.strip().lower()
                prop_value = value.strip()
                if prop_name:
                    properties[prop_name] = prop_value
            if not properties:
                continue

            for target in mapped_targets:
                target_style = style_map.get(target)
                if target_style is None:
                    continue
                for prop_name, prop_value in properties.items():
                    if target == 'document':
                        document_prop_map = {
                            'page-width': 'page_width',
                            'page-height': 'page_height',
                            'margin-top': 'margin_top',
                            'margin-right': 'margin_right',
                            'margin-bottom': 'margin_bottom',
                            'margin-left': 'margin_left',
                            'header': 'header',
                            'footer': 'footer',
                            'gutter': 'gutter',
                            'column-space': 'column_space',
                            'line-pitch': 'line_pitch',
                        }
                        if prop_name in ('default-header-text', 'header-text'):
                            target_style['default_header_text'] = self._parse_css_string(
                                prop_value,
                                target_style.get('default_header_text', ''),
                            )
                            continue
                        if prop_name in ('first-page-header-text', 'first-header-text'):
                            target_style['first_page_header_text'] = self._parse_css_string(
                                prop_value,
                                target_style.get('first_page_header_text', ''),
                            )
                            continue
                        if prop_name == 'header-font-family':
                            target_style['header_font_family'] = self._parse_css_string(
                                prop_value,
                                target_style.get('header_font_family', 'Times New Roman'),
                            )
                            continue
                        if prop_name == 'header-font-size':
                            target_style['header_font_size_half_points'] = self._parse_css_length_to_half_points(
                                prop_value,
                                target_style.get('header_font_size_half_points', 22),
                            )
                            continue
                        if prop_name == 'header-font-weight':
                            target_style['header_bold'] = self._parse_css_bool(
                                prop_value,
                                target_style.get('header_bold', False),
                            )
                            continue
                        if prop_name == 'header-text-align':
                            target_style['header_text_align'] = self._normalize_docx_alignment(
                                prop_value,
                                target_style.get('header_text_align', 'center'),
                            )
                            continue
                        if prop_name in ('orientation', 'page-orientation'):
                            target_style['page_orientation'] = self._normalize_docx_orientation(
                                prop_value,
                                target_style.get('page_orientation', 'portrait'),
                            )
                            continue
                        if prop_name == 'gutter-position':
                            target_style['gutter_position'] = self._parse_css_string(
                                prop_value,
                                target_style.get('gutter_position', 'left'),
                            ).lower()
                            continue
                        if prop_name == 'page-numbering':
                            target_style['page_numbering'] = self._parse_css_bool(
                                prop_value,
                                target_style.get('page_numbering', True),
                            )
                            continue
                        if prop_name == 'page-number-align':
                            target_style['page_number_align'] = self._normalize_docx_alignment(
                                prop_value,
                                target_style.get('page_number_align', 'center'),
                            )
                            continue
                        if prop_name == 'page-number-font-family':
                            target_style['page_number_font_family'] = self._parse_css_string(
                                prop_value,
                                target_style.get('page_number_font_family', 'Times New Roman'),
                            )
                            continue
                        if prop_name == 'page-number-font-size':
                            target_style['page_number_font_size_half_points'] = self._parse_css_length_to_half_points(
                                prop_value,
                                target_style.get('page_number_font_size_half_points', 18),
                            )
                            continue
                        if prop_name == 'page-number-font-weight':
                            target_style['page_number_bold'] = self._parse_css_bool(
                                prop_value,
                                target_style.get('page_number_bold', False),
                            )
                            continue
                        if prop_name == 'page-number-line-height':
                            target_style['page_number_line_height'] = self._parse_css_length_to_twips(
                                prop_value,
                                target_style.get('page_number_line_height', 180),
                            )
                            continue
                        if prop_name == 'page-number-position':
                            target_style['page_number_position_half_points'] = self._parse_css_length_to_half_points(
                                prop_value,
                                target_style.get('page_number_position_half_points', 0),
                            )
                            continue
                        if prop_name == 'header-margin-top':
                            target_style['header_spacing_before'] = self._parse_css_length_to_twips(
                                prop_value,
                                target_style.get('header_spacing_before', 0),
                            )
                            continue
                        if prop_name == 'header-margin-bottom':
                            target_style['header_spacing_after'] = self._parse_css_length_to_twips(
                                prop_value,
                                target_style.get('header_spacing_after', 120),
                            )
                            continue
                        mapped_key = document_prop_map.get(prop_name)
                        if mapped_key:
                            target_style[mapped_key] = self._parse_css_length_to_twips(
                                prop_value,
                                target_style.get(mapped_key, 0),
                            )
                        continue

                    if prop_name == 'font-family':
                        target_style['font_family'] = prop_value.strip().strip('"').strip("'")
                    elif prop_name == 'font-size':
                        target_style['font_size_half_points'] = self._parse_css_length_to_half_points(
                            prop_value,
                            target_style.get('font_size_half_points', 24),
                        )
                    elif prop_name == 'font-weight':
                        target_style['bold'] = self._parse_css_bool(
                            prop_value,
                            target_style.get('bold', False),
                        )
                    elif prop_name == 'text-align':
                        target_style['text_align'] = self._normalize_docx_alignment(
                            prop_value,
                            target_style.get('text_align', 'left'),
                        )
                    elif prop_name == 'margin-top':
                        target_style['spacing_before'] = self._parse_css_length_to_twips(
                            prop_value,
                            target_style.get('spacing_before', 0),
                        )
                    elif prop_name == 'margin-bottom':
                        target_style['spacing_after'] = self._parse_css_length_to_twips(
                            prop_value,
                            target_style.get('spacing_after', 0),
                        )
                    elif prop_name == 'line-height':
                        target_style['line_height'] = self._parse_css_length_to_twips(
                            prop_value,
                            target_style.get('line_height', 0),
                        )
                    elif prop_name == 'margin-left':
                        target_style['indent_left'] = self._parse_css_length_to_twips(
                            prop_value,
                            target_style.get('indent_left', 0),
                        )
                    elif prop_name in ('hanging-indent', 'text-indent'):
                        parsed_indent = self._parse_css_length_to_twips(
                            prop_value,
                            target_style.get('indent_hanging', 0),
                        )
                        target_style['indent_hanging'] = abs(parsed_indent)
                    elif prop_name == 'restart':
                        target_style['restart'] = self._parse_css_bool(
                            prop_value,
                            target_style.get('restart', False),
                        )

        return style_map

    @staticmethod
    def _build_docx_run_properties_xml(
        font_family='Times New Roman',
        bold=False,
        font_size_half_points=24,
        clear_background=False,
        position_half_points=0,
    ):
        resolved_font = (font_family or 'Times New Roman').replace('"', '').replace("'", '')
        bold_xml = '<w:b/><w:bCs/>' if bold else ''
        clear_background_xml = ''
        if clear_background:
            clear_background_xml = '<w:highlight w:val="none"/><w:shd w:val="nil"/>'
        position_xml = ''
        if position_half_points:
            position_xml = f'<w:position w:val="{int(position_half_points)}"/>'
        return (
            '<w:rPr>'
            f'<w:rFonts w:ascii="{resolved_font}" w:hAnsi="{resolved_font}" '
            f'w:eastAsia="{resolved_font}" w:cs="{resolved_font}"/>'
            f'{bold_xml}'
            f'{clear_background_xml}'
            f'{position_xml}'
            f'<w:sz w:val="{int(font_size_half_points)}"/>'
            f'<w:szCs w:val="{int(font_size_half_points)}"/>'
            '</w:rPr>'
        )

    @classmethod
    def _build_docx_run_xml(
        cls,
        text_value,
        font_family='Times New Roman',
        bold=False,
        font_size_half_points=24,
        clear_background=False,
        position_half_points=0,
    ):
        value = '' if text_value is None else str(text_value)
        escaped_text = html_lib.escape(value, quote=False)
        needs_preserve = (
            value.startswith(' ')
            or value.endswith(' ')
            or '  ' in value
        )
        preserve_attr = ' xml:space="preserve"' if needs_preserve else ''
        return (
            '<w:r>'
            f'{cls._build_docx_run_properties_xml(font_family, bold, font_size_half_points, clear_background, position_half_points)}'
            f'<w:t{preserve_attr}>{escaped_text}</w:t>'
            '</w:r>'
        )

    @staticmethod
    def _normalize_docx_list_level(list_level, max_level=1):
        if list_level is None:
            return None
        try:
            normalized_level = int(list_level)
        except (TypeError, ValueError):
            normalized_level = 0
        if normalized_level < 0:
            normalized_level = 0
        if max_level is not None and normalized_level > max_level:
            normalized_level = max_level
        return normalized_level

    @staticmethod
    def _docx_numbering_num_id(list_kind):
        normalized_kind = (list_kind or '').strip().lower()
        return 2 if normalized_kind == 'unordered' else 1

    @staticmethod
    def _build_docx_numbering_level_xml(
        level_index,
        num_format,
        level_text,
        indent_left,
        indent_hanging,
        font_family,
        font_size_half_points,
        restart_xml='',
        marker_font_family=None,
    ):
        resolved_font = str(marker_font_family or font_family or 'Times New Roman').replace('"', '').replace("'", '')
        escaped_font = html_lib.escape(resolved_font, quote=True)
        escaped_level_text = html_lib.escape(level_text or '', quote=True)
        return (
            f'<w:lvl w:ilvl="{int(level_index)}">'
            '<w:start w:val="1"/>'
            f'{restart_xml}'
            f'<w:numFmt w:val="{html_lib.escape(num_format or "decimal", quote=True)}"/>'
            f'<w:lvlText w:val="{escaped_level_text}"/>'
            '<w:lvlJc w:val="left"/>'
            '<w:suff w:val="tab"/>'
            '<w:pPr>'
            f'<w:tabs><w:tab w:val="num" w:pos="{int(indent_left)}"/></w:tabs>'
            f'<w:ind w:left="{int(indent_left)}" w:hanging="{int(indent_hanging)}"/>'
            '</w:pPr>'
            '<w:rPr>'
            f'<w:rFonts w:ascii="{escaped_font}" w:hAnsi="{escaped_font}" '
            f'w:eastAsia="{escaped_font}" w:cs="{escaped_font}"/>'
            f'<w:sz w:val="{int(font_size_half_points)}"/>'
            f'<w:szCs w:val="{int(font_size_half_points)}"/>'
            '</w:rPr>'
            '</w:lvl>'
        )

    def _build_docx_runs_xml(self, text_value, run_style):
        def build_text_with_breaks(raw_text, style):
            parts = str(raw_text or '').split(LOR_LINE_BREAK_TOKEN)
            run_chunks = []
            run_properties_xml = self._build_docx_run_properties_xml(**style)
            for part_index, part_text in enumerate(parts):
                if part_text:
                    run_chunks.append(self._build_docx_run_xml(part_text, **style))
                if part_index < len(parts) - 1:
                    run_chunks.append(f'<w:r>{run_properties_xml}<w:br/></w:r>')
            return ''.join(run_chunks)

        segments = re.split(r'(\*\*.*?\*\*)', text_value or '')
        run_chunks = []
        for segment in segments:
            if not segment:
                continue
            is_bold_segment = segment.startswith('**') and segment.endswith('**') and len(segment) >= 4
            if is_bold_segment:
                chunk_text = segment[2:-2]
                if not chunk_text:
                    continue
                bold_style = dict(run_style)
                bold_style['bold'] = True
                run_chunks.append(build_text_with_breaks(chunk_text, bold_style))
            else:
                run_chunks.append(build_text_with_breaks(segment, run_style))
        return ''.join(run_chunks) if run_chunks else self._build_docx_run_xml(text_value, **run_style)

    def _build_docx_paragraph_xml(
        self,
        text_line,
        style_map,
        title_style=False,
        list_level=None,
        list_kind=None,
        style_key=None,
        gap_after_twips=0,
        preserve_empty=False,
    ):
        text_value = '' if text_line is None else str(text_line)
        if not text_value and preserve_empty:
            text_value = ' '
        if not text_value:
            return '<w:p/>'

        body_style = style_map.get('body', {})
        paragraph_style = dict(style_map.get('paragraph', {}))
        style_overrides = style_map.get(style_key) if style_key else None
        if isinstance(style_overrides, dict):
            paragraph_style.update(style_overrides)
        title_block_style = style_map.get('title', {})

        run_style = {
            'font_family': body_style.get('font_family', 'Times New Roman'),
            'font_size_half_points': int(body_style.get('font_size_half_points', 24)),
            'bold': bool(body_style.get('bold', False)),
        }
        for key in ('font_family', 'font_size_half_points', 'bold'):
            if key in paragraph_style:
                run_style[key] = paragraph_style[key]
        if title_style:
            for key in ('font_family', 'font_size_half_points', 'bold'):
                if key in title_block_style:
                    run_style[key] = title_block_style[key]

        effective_paragraph_style = dict(paragraph_style)
        if title_style:
            effective_paragraph_style.update(title_block_style)

        effective_align = self._normalize_docx_alignment(
            effective_paragraph_style.get('text_align', 'left'),
            default='left',
        )
        # LOR DOCX output must always use zero paragraph spacing before/after,
        # except for explicit LOR gap modifiers that request fixed after spacing.
        spacing_before = 0
        spacing_after = int(gap_after_twips or 0)
        line_height = int(effective_paragraph_style.get('line_height', body_style.get('line_height', 0)))

        paragraph_props = []
        paragraph_props.append(f'<w:jc w:val="{effective_align}"/>')
        spacing_attrs = [
            f'w:before="{spacing_before}"',
            f'w:after="{spacing_after}"',
        ]
        if line_height:
            spacing_attrs.append(f'w:line="{line_height}"')
            spacing_attrs.append('w:lineRule="auto"')
        paragraph_props.append(f"<w:spacing {' '.join(spacing_attrs)}/>")

        normalized_list_level = self._normalize_docx_list_level(list_level, max_level=1)
        if normalized_list_level is not None:
            list_style = style_map.get(f'list_level_{normalized_list_level}', {})
            indent_left = int(list_style.get('indent_left', 0))
            indent_hanging = int(list_style.get('indent_hanging', 0))
            num_id = self._docx_numbering_num_id(list_kind)
            paragraph_props.append(
                '<w:numPr>'
                f'<w:ilvl w:val="{normalized_list_level}"/>'
                f'<w:numId w:val="{num_id}"/>'
                '</w:numPr>'
            )
            paragraph_props.append(
                f'<w:ind w:left="{indent_left}" w:hanging="{indent_hanging}"/>'
            )

        ppr_xml = f"<w:pPr>{''.join(paragraph_props)}</w:pPr>" if paragraph_props else ''
        runs_xml = self._build_docx_runs_xml(text_value, run_style)
        return (
            '<w:p>'
            f'{ppr_xml}'
            f'{runs_xml}'
            '</w:p>'
        )

    def _build_docx_header_xml(self, header_text, document_style, body_style):
        run_style = {
            'font_family': document_style.get('header_font_family', body_style.get('font_family', 'Times New Roman')),
            'font_size_half_points': int(
                document_style.get('header_font_size_half_points', body_style.get('font_size_half_points', 24))
            ),
            'bold': bool(document_style.get('header_bold', False)),
        }
        align = self._normalize_docx_alignment(
            document_style.get('header_text_align', 'center'),
            default='center',
        )
        spacing_before = int(document_style.get('header_spacing_before', 0))
        spacing_after = int(document_style.get('header_spacing_after', 120))
        header_text_value = str(header_text or '')

        spacing_xml = (
            f'<w:spacing w:before="{spacing_before}" w:after="{spacing_after}"/>'
        )

        if header_text_value:
            runs_xml = self._build_docx_runs_xml(header_text_value, run_style)
            paragraph_xml = (
                '<w:p>'
                '<w:pPr>'
                f'<w:jc w:val="{align}"/>'
                f'{spacing_xml}'
                '</w:pPr>'
                f'{runs_xml}'
                '</w:p>'
            )
        else:
            paragraph_xml = '<w:p/>'

        return (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:hdr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            f'{paragraph_xml}'
            '</w:hdr>'
        )

    def _build_docx_field_runs_xml(self, field_instruction, run_style, default_display='1'):
        run_properties_xml = self._build_docx_run_properties_xml(**run_style)
        instruction_text = html_lib.escape(str(field_instruction or '').strip(), quote=False)
        return (
            f'<w:r>{run_properties_xml}<w:fldChar w:fldCharType="begin" w:dirty="true"/></w:r>'
            f'<w:r>{run_properties_xml}<w:instrText xml:space="preserve"> {instruction_text} </w:instrText></w:r>'
            f'<w:r>{run_properties_xml}<w:fldChar w:fldCharType="separate"/></w:r>'
            f'{self._build_docx_run_xml(default_display, **run_style)}'
            f'<w:r>{run_properties_xml}<w:fldChar w:fldCharType="end"/></w:r>'
        )

    def _build_docx_footer_xml(self, document_style, body_style):
        run_style = {
            'font_family': document_style.get(
                'page_number_font_family',
                body_style.get('font_family', 'Times New Roman'),
            ),
            'font_size_half_points': int(
                document_style.get(
                    'page_number_font_size_half_points',
                    body_style.get('font_size_half_points', 24),
                )
            ),
            'bold': bool(document_style.get('page_number_bold', False)),
            'clear_background': True,
            'position_half_points': int(document_style.get('page_number_position_half_points', 0)),
        }
        align = self._normalize_docx_alignment(
            document_style.get('page_number_align', 'center'),
            default='center',
        )
        footer_runs_xml = self._build_docx_field_runs_xml('PAGE   \\* MERGEFORMAT', run_style)
        return (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:ftr xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            '<w:sdt>'
            '<w:sdtPr>'
            '<w:id w:val="-954637309"/>'
            '<w:docPartObj>'
            '<w:docPartGallery w:val="Page Numbers (Bottom of Page)"/>'
            '<w:docPartUnique/>'
            '</w:docPartObj>'
            '</w:sdtPr>'
            '<w:sdtEndPr><w:rPr><w:noProof/></w:rPr></w:sdtEndPr>'
            '<w:sdtContent>'
            '<w:p>'
            '<w:pPr>'
            '<w:pStyle w:val="Footer"/>'
            f'<w:jc w:val="{align}"/>'
            '</w:pPr>'
            f'{footer_runs_xml}'
            '</w:p>'
            '</w:sdtContent>'
            '</w:sdt>'
            '</w:ftr>'
        )

    def _build_docx_from_text(self, body_text, title='Audit Representation Letter', lor_styles=None):
        blocks = self._extract_lor_blocks(body_text)
        if not blocks:
            blocks = [{'text': '', 'title_style': False, 'list_level': None}]
        style_map = {
            name: dict(values)
            for name, values in (lor_styles or self._default_lor_docx_styles()).items()
        }
        # Match the known-good reference lor.docx footer placement regardless of
        # company-specific CSS overrides stored in the database.
        document_style = style_map.setdefault('document', {})
        document_style['footer'] = 113
        document_style['page_number_align'] = 'center'
        document_style['page_number_position_half_points'] = 0

        paragraph_xml_parts = []
        for block in blocks:
            paragraph_xml_parts.append(
                self._build_docx_paragraph_xml(
                    block.get('text', ''),
                    style_map,
                    title_style=bool(block.get('title_style')),
                    list_level=block.get('list_level'),
                    list_kind=block.get('list_kind'),
                    style_key=block.get('style_key'),
                    gap_after_twips=block.get('gap_after_twips', 0),
                    preserve_empty=bool(block.get('preserve_empty', False)),
                )
            )
        paragraph_xml = ''.join(paragraph_xml_parts)
        document_style = style_map.get('document', {})
        body_style = style_map.get('body', {})
        default_header_text = str(document_style.get('default_header_text', '') or '')
        first_page_header_text = str(document_style.get('first_page_header_text', '') or '')
        header_enabled = bool(default_header_text or first_page_header_text)
        page_numbering_enabled = bool(document_style.get('page_numbering', True))
        page_orientation = self._normalize_docx_orientation(
            document_style.get('page_orientation', 'portrait'),
            default='portrait',
        )
        gutter_position = str(document_style.get('gutter_position', 'left') or 'left').strip().lower()

        next_relation_id = 2
        default_header_rel_id = None
        first_page_header_rel_id = None
        default_footer_rel_id = None
        first_page_footer_rel_id = None

        if header_enabled:
            default_header_rel_id = f'rId{next_relation_id}'
            next_relation_id += 1
            first_page_header_rel_id = f'rId{next_relation_id}'
            next_relation_id += 1

        if page_numbering_enabled:
            default_footer_rel_id = f'rId{next_relation_id}'
            next_relation_id += 1
            if header_enabled:
                first_page_footer_rel_id = f'rId{next_relation_id}'
                next_relation_id += 1

        section_reference_parts = []
        if default_header_rel_id:
            section_reference_parts.append(
                f'<w:headerReference w:type="default" r:id="{default_header_rel_id}"/>'
            )
        if first_page_header_rel_id:
            section_reference_parts.append(
                f'<w:headerReference w:type="first" r:id="{first_page_header_rel_id}"/>'
            )
        if default_footer_rel_id:
            section_reference_parts.append(
                f'<w:footerReference w:type="default" r:id="{default_footer_rel_id}"/>'
            )
        if first_page_footer_rel_id:
            section_reference_parts.append(
                f'<w:footerReference w:type="first" r:id="{first_page_footer_rel_id}"/>'
            )
        if header_enabled:
            section_reference_parts.append('<w:titlePg/>')

        gutter_position_xml = '<w:gutterAtTop/>' if gutter_position == 'top' else ''

        document_xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" '
            'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
            '<w:body>'
            f'{paragraph_xml}'
            '<w:sectPr>'
            f'{"".join(section_reference_parts)}'
            f'<w:pgSz w:w="{int(document_style.get("page_width", 11906))}" '
            f'w:h="{int(document_style.get("page_height", 16838))}" '
            f'w:orient="{page_orientation}"/>'
            f'<w:pgMar w:top="{int(document_style.get("margin_top", 1928))}" '
            f'w:right="{int(document_style.get("margin_right", 1440))}" '
            f'w:bottom="{int(document_style.get("margin_bottom", 850))}" '
            f'w:left="{int(document_style.get("margin_left", 1440))}" '
            f'w:header="{int(document_style.get("header", 720))}" '
            f'w:footer="{int(document_style.get("footer", 720))}" '
            f'w:gutter="{int(document_style.get("gutter", 0))}"/>'
            f'{gutter_position_xml}'
            f'<w:cols w:space="{int(document_style.get("column_space", 720))}"/>'
            f'<w:docGrid w:linePitch="{int(document_style.get("line_pitch", 360))}"/>'
            '</w:sectPr>'
            '</w:body>'
            '</w:document>'
        )

        generated_on = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace('+00:00', 'Z')
        escaped_title = html_lib.escape(title or 'Document', quote=False)
        core_xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<cp:coreProperties '
            'xmlns:cp="http://schemas.openxmlformats.org/package/2006/metadata/core-properties" '
            'xmlns:dc="http://purl.org/dc/elements/1.1/" '
            'xmlns:dcterms="http://purl.org/dc/terms/" '
            'xmlns:dcmitype="http://purl.org/dc/dcmitype/" '
            'xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
            f'<dc:title>{escaped_title}</dc:title>'
            '<dc:creator>Odoo LOR Report</dc:creator>'
            '<cp:lastModifiedBy>Odoo LOR Report</cp:lastModifiedBy>'
            f'<dcterms:created xsi:type="dcterms:W3CDTF">{generated_on}</dcterms:created>'
            f'<dcterms:modified xsi:type="dcterms:W3CDTF">{generated_on}</dcterms:modified>'
            '</cp:coreProperties>'
        )

        app_xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Properties xmlns="http://schemas.openxmlformats.org/officeDocument/2006/extended-properties" '
            'xmlns:vt="http://schemas.openxmlformats.org/officeDocument/2006/docPropsVTypes">'
            '<Application>Odoo LOR Report</Application>'
            '</Properties>'
        )

        rels_xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            '<Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" '
            'Target="word/document.xml"/>'
            '<Relationship Id="rId2" '
            'Type="http://schemas.openxmlformats.org/package/2006/relationships/metadata/core-properties" '
            'Target="docProps/core.xml"/>'
            '<Relationship Id="rId3" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/extended-properties" '
            'Target="docProps/app.xml"/>'
            '</Relationships>'
        )

        base_font = (body_style.get('font_family', 'Times New Roman') or 'Times New Roman')
        base_font = str(base_font).replace('"', '').replace("'", '')
        base_font_size = int(body_style.get('font_size_half_points', 24))
        list_level_0_style = style_map.get('list_level_0', {})
        list_level_1_style = style_map.get('list_level_1', {})
        list_0_indent_left = int(list_level_0_style.get('indent_left', 720))
        list_0_indent_hanging = int(list_level_0_style.get('indent_hanging', 360))
        list_1_indent_left = int(list_level_1_style.get('indent_left', 1440))
        list_1_indent_hanging = int(list_level_1_style.get('indent_hanging', 360))
        list_1_restart = bool(list_level_1_style.get('restart', True))
        list_1_restart_xml = '<w:lvlRestart w:val="1"/>' if list_1_restart else ''
        ordered_level_0_xml = self._build_docx_numbering_level_xml(
            level_index=0,
            num_format='decimal',
            level_text='%1.',
            indent_left=list_0_indent_left,
            indent_hanging=list_0_indent_hanging,
            font_family=base_font,
            font_size_half_points=base_font_size,
        )
        ordered_level_1_xml = self._build_docx_numbering_level_xml(
            level_index=1,
            num_format='lowerLetter',
            level_text='%2.',
            indent_left=list_1_indent_left,
            indent_hanging=list_1_indent_hanging,
            font_family=base_font,
            font_size_half_points=base_font_size,
            restart_xml=list_1_restart_xml,
        )
        bullet_level_0_xml = self._build_docx_numbering_level_xml(
            level_index=0,
            num_format='bullet',
            level_text='•',
            indent_left=list_0_indent_left,
            indent_hanging=list_0_indent_hanging,
            font_family=base_font,
            font_size_half_points=base_font_size,
        )
        bullet_level_1_xml = self._build_docx_numbering_level_xml(
            level_index=1,
            num_format='bullet',
            level_text='•',
            indent_left=list_1_indent_left,
            indent_hanging=list_1_indent_hanging,
            font_family=base_font,
            font_size_half_points=base_font_size,
        )
        default_header_xml = ''
        first_page_header_xml = ''
        default_footer_xml = ''
        first_page_footer_xml = ''
        document_rels_parts = [
            '<Relationship Id="rId1" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/numbering" '
            'Target="numbering.xml"/>'
        ]
        if header_enabled:
            default_header_xml = self._build_docx_header_xml(
                default_header_text,
                document_style,
                body_style,
            )
            first_page_header_xml = self._build_docx_header_xml(
                first_page_header_text,
                document_style,
                body_style,
            )
            document_rels_parts.extend([
                f'<Relationship Id="{default_header_rel_id}" '
                'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/header" '
                'Target="header1.xml"/>',
                f'<Relationship Id="{first_page_header_rel_id}" '
                'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/header" '
                'Target="header2.xml"/>',
            ])
        if page_numbering_enabled:
            default_footer_xml = self._build_docx_footer_xml(
                document_style,
                body_style,
            )
            document_rels_parts.append(
                f'<Relationship Id="{default_footer_rel_id}" '
                'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer" '
                'Target="footer1.xml"/>'
            )
            if first_page_footer_rel_id:
                first_page_footer_xml = self._build_docx_footer_xml(
                    document_style,
                    body_style,
                )
                document_rels_parts.append(
                    f'<Relationship Id="{first_page_footer_rel_id}" '
                    'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/footer" '
                    'Target="footer2.xml"/>'
                )

        document_rels_xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
            f'{"".join(document_rels_parts)}'
            '</Relationships>'
        )

        numbering_xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<w:numbering xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
            '<w:abstractNum w:abstractNumId="0">'
            '<w:nsid w:val="4C4F5231"/>'
            '<w:multiLevelType w:val="hybridMultilevel"/>'
            '<w:tmpl w:val="4C4F5231"/>'
            f'{ordered_level_0_xml}'
            f'{ordered_level_1_xml}'
            '</w:abstractNum>'
            '<w:abstractNum w:abstractNumId="1">'
            '<w:nsid w:val="4C4F5232"/>'
            '<w:multiLevelType w:val="hybridMultilevel"/>'
            '<w:tmpl w:val="4C4F5232"/>'
            f'{bullet_level_0_xml}'
            f'{bullet_level_1_xml}'
            '</w:abstractNum>'
            '<w:num w:numId="1"><w:abstractNumId w:val="0"/></w:num>'
            '<w:num w:numId="2"><w:abstractNumId w:val="1"/></w:num>'
            '</w:numbering>'
        )

        header_overrides_xml = ''
        if header_enabled:
            header_overrides_xml = (
                '<Override PartName="/word/header1.xml" '
                'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.header+xml"/>'
                '<Override PartName="/word/header2.xml" '
                'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.header+xml"/>'
            )
        footer_overrides_xml = ''
        if page_numbering_enabled:
            footer_overrides_xml = (
                '<Override PartName="/word/footer1.xml" '
                'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"/>'
            )
            if first_page_footer_rel_id:
                footer_overrides_xml += (
                    '<Override PartName="/word/footer2.xml" '
                    'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.footer+xml"/>'
                )

        content_types_xml = (
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
            '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
            '<Default Extension="xml" ContentType="application/xml"/>'
            '<Override PartName="/word/document.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>'
            '<Override PartName="/word/numbering.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml"/>'
            f'{header_overrides_xml}'
            f'{footer_overrides_xml}'
            '<Override PartName="/docProps/core.xml" '
            'ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>'
            '<Override PartName="/docProps/app.xml" '
            'ContentType="application/vnd.openxmlformats-officedocument.extended-properties+xml"/>'
            '</Types>'
        )

        output_buffer = BytesIO()
        with ZipFile(output_buffer, mode='w', compression=ZIP_DEFLATED) as archive:
            archive.writestr('[Content_Types].xml', content_types_xml)
            archive.writestr('_rels/.rels', rels_xml)
            archive.writestr('docProps/app.xml', app_xml)
            archive.writestr('docProps/core.xml', core_xml)
            archive.writestr('word/document.xml', document_xml)
            archive.writestr('word/_rels/document.xml.rels', document_rels_xml)
            archive.writestr('word/numbering.xml', numbering_xml)
            if header_enabled:
                archive.writestr('word/header1.xml', default_header_xml)
                archive.writestr('word/header2.xml', first_page_header_xml)
            if page_numbering_enabled:
                archive.writestr('word/footer1.xml', default_footer_xml)
                if first_page_footer_rel_id:
                    archive.writestr('word/footer2.xml', first_page_footer_xml)
        return output_buffer.getvalue()

    @staticmethod
    def _build_lor_filename(record):
        company_name = (getattr(record.company_id, 'name', '') or '').strip()
        safe_company_name = re.sub(r'[^A-Za-z0-9]+', '_', company_name).strip('_')
        if not safe_company_name:
            safe_company_name = f'company_{record.id}'
        return f'Audit_Representation_Letter_{safe_company_name}.docx'

    @staticmethod
    def _extract_error_summary_and_issues(error, default_summary):
        raw = str(error or '').replace('\r', '\n')
        lines = [line.strip() for line in raw.split('\n') if line.strip()]
        if not lines:
            return default_summary, []

        summary = lines[0]
        issues = []
        for line in lines[1:]:
            cleaned = line.lstrip('-*• ').strip()
            if cleaned:
                issues.append(cleaned)

        if summary.startswith(('-', '*', '•')):
            cleaned_summary = summary.lstrip('-*• ').strip()
            summary = default_summary
            if cleaned_summary:
                issues.insert(0, cleaned_summary)

        return summary or default_summary, issues

    @staticmethod
    def _render_html_response(title, body_html, status=200):
        safe_title = html_lib.escape(title or 'LOR')
        page = f"""<!doctype html>
<html>
  <head>
    <meta charset="utf-8"/>
    <title>{safe_title}</title>
    <style>
      body {{
        font-family: Arial, sans-serif;
        margin: 0;
        background: #f5f7fb;
        color: #1f2937;
      }}
      .page {{
        max-width: 720px;
        margin: 48px auto;
        background: #fff;
        border: 1px solid #d7deea;
        border-radius: 10px;
        padding: 24px;
        box-shadow: 0 10px 28px rgba(15, 23, 42, 0.08);
      }}
      h1 {{
        margin-top: 0;
        font-size: 22px;
      }}
      .btn {{
        display: inline-block;
        padding: 10px 14px;
        border-radius: 6px;
        background: #4b5563;
        color: #fff;
        text-decoration: none;
      }}
      ul {{
        padding-left: 20px;
      }}
    </style>
  </head>
  <body>
    <div class="page">{body_html}</div>
  </body>
</html>"""
        return request.make_response(
            page,
            headers=[('Content-Type', 'text/html; charset=utf-8')],
            status=status,
        )

    def _render_editor_error_response(self, title, summary, issues=None, back_url=None, status=400):
        safe_title = html_lib.escape(title or 'Error')
        safe_summary = html_lib.escape(summary or 'Something went wrong.')
        issue_items = ''.join(f"<li>{html_lib.escape(issue)}</li>" for issue in (issues or []))
        issue_list = f'<ul>{issue_items}</ul>' if issue_items else ''
        back_link = (
            f'<a class="btn" href="{html_lib.escape(back_url)}">Back</a>'
            if back_url else ''
        )
        body = f"""
<h1>{safe_title}</h1>
<p>{safe_summary}</p>
{issue_list}
<p>{back_link}</p>
"""
        return self._render_html_response(title, body, status=status)

    @staticmethod
    def _forbidden_response(message='Forbidden'):
        return request.make_response(
            message,
            headers=[('Content-Type', 'text/plain; charset=utf-8')],
            status=403,
        )

    @staticmethod
    def _validate_lor_record(record):
        if hasattr(record, '_validate_lor_settings'):
            record._validate_lor_settings()
            return
        if (
            (getattr(record, 'signature_date_mode', '') or '').strip().lower() == 'manual'
            and not getattr(record, 'signature_manual_date', False)
        ):
            raise ValidationError(
                "Please provide Manual Signature Date when signature placeholder date mode is set to Manual date."
            )

    @staticmethod
    def _get_lor_extra_main_items(record):
        if hasattr(record, '_get_lor_extra_item_texts'):
            return record._get_lor_extra_item_texts()

        extra_lines = getattr(record, 'extra_item_line_ids', False)
        if not extra_lines:
            return []

        return [
            (line.item_text or '').strip()
            for line in extra_lines.sorted(key=lambda line: (line.sequence or 0, line.id))
            if (line.item_text or '').strip()
        ]

    @staticmethod
    def _get_lor_back_url(record):
        return f'/web#id={record.id}&model={record._name}&view_type=form'

    def _generate_lor_docx_response(self, record):
        company = self._get_lor_company(record)
        if company.id not in request.env.user.company_ids.ids:
            return self._forbidden_response("This LOR belongs to a company not allowed for your user.")

        template_text = self._get_lor_template_content_for_company(company)
        if not template_text:
            return self._render_editor_error_response(
                'Audit Representation Letter Error',
                'LOR template source was not found.',
                ['Set the LOR HTML source on the company form, or restore the module defaults.'],
                back_url=self._get_lor_back_url(record),
                status=500,
            )

        lor_css_text = self._get_lor_css_content_for_company(company)
        lor_styles = self._parse_lor_css_styles(lor_css_text)

        try:
            self._validate_lor_record(record)
            extra_main_items = self._get_lor_extra_main_items(record)
            placeholder_values = self._build_lor_placeholder_values(record)
            filled_lor_content = self._render_lor_template_content_from_source(
                template_text,
                placeholder_values,
                extra_main_items=extra_main_items,
            )
            docx_content = self._build_docx_from_text(
                filled_lor_content,
                title='Audit Representation Letter',
                lor_styles=lor_styles,
            )
        except Exception as error:
            _logger.exception("Audit representation letter DOCX generation failed: %s", error)
            summary, issues = self._extract_error_summary_and_issues(
                error,
                'Unable to generate the audit representation letter.',
            )
            return self._render_editor_error_response(
                'Audit Representation Letter Error',
                summary,
                issues,
                back_url=self._get_lor_back_url(record),
                status=500,
            )

        filename = self._build_lor_filename(record)
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

    @http.route('/lor_report/docx/<int:wizard_id>', type='http', auth='user')
    def generate_lor_docx(self, wizard_id, **kwargs):
        wizard = request.env['lor.report.wizard'].browse(wizard_id)
        if not wizard.exists():
            return request.not_found()
        return self._generate_lor_docx_response(wizard)

    @http.route('/lor_report/docx/audit/<int:wizard_id>', type='http', auth='user')
    def generate_audit_lor_docx(self, wizard_id, **kwargs):
        wizard = request.env['audit.report'].browse(wizard_id)
        if not wizard.exists():
            return request.not_found()
        return self._generate_lor_docx_response(wizard)
