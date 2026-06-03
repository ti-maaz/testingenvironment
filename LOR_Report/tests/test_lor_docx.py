import re
from io import BytesIO
from unittest.mock import patch
from zipfile import ZipFile

from odoo.tests import TransactionCase, tagged

from odoo.addons.LOR_Report.controllers.main import LorReportController
from odoo.addons.LOR_Report.hooks import post_init_hook
from odoo.addons.LOR_Report.models import res_company as res_company_model
from odoo.addons.LOR_Report.models.res_company import get_default_lor_css_source


@tagged('post_install', '-at_install')
class TestLorReportDocx(TransactionCase):
    def test_lor_template_render_accepts_extra_main_items_keyword(self):
        controller = LorReportController()
        html = '<html><body><ol class="list-level-0"><li>Base item</li></ol></body></html>'

        rendered = controller._render_lor_template_content_from_source(
            html,
            placeholder_values={},
            extra_main_items=['Extra item'],
        )

        self.assertIn('Base item', rendered)
        self.assertIn('Extra item', rendered)

    def test_lor_html_spacer_line_class_preserves_blank_enter_line(self):
        controller = LorReportController()
        blocks = controller._extract_lor_blocks_from_html(
            '<html><body><p>First</p><p class="spacer-line"></p><p>Second</p></body></html>'
        )

        self.assertEqual(blocks[1]['style_key'], 'spacer_line')
        self.assertEqual(blocks[1]['text'], '')
        self.assertTrue(blocks[1]['preserve_empty'])

    def test_lor_docx_numbering_xml_uses_word_friendly_nested_ordered_lists(self):
        controller = LorReportController()
        html = (
            '<html><body>'
            '<ol class="list-level-0">'
            '<li>Parent item'
            '<ol class="list-level-1"><li>Child item</li></ol>'
            '</li>'
            '</ol>'
            '</body></html>'
        )

        docx_content = controller._build_docx_from_text(
            html,
            lor_styles=controller._default_lor_docx_styles(),
        )

        with ZipFile(BytesIO(docx_content)) as archive:
            numbering_xml = archive.read('word/numbering.xml').decode('utf-8')
            document_xml = archive.read('word/document.xml').decode('utf-8')

        self.assertIn('<w:multiLevelType w:val="hybridMultilevel"/>', numbering_xml)
        self.assertIn('<w:suff w:val="tab"/>', numbering_xml)
        self.assertIn('<w:tabs><w:tab w:val="num" w:pos="720"/></w:tabs>', numbering_xml)
        self.assertIn('<w:tabs><w:tab w:val="num" w:pos="1440"/></w:tabs>', numbering_xml)
        self.assertIn('<w:ilvl w:val="1"/>', document_xml)
        self.assertIn('<w:numId w:val="1"/>', document_xml)

    def test_lor_docx_preserves_unordered_lists_as_bullets(self):
        controller = LorReportController()
        html = '<html><body><ul><li>Bullet item</li></ul></body></html>'

        docx_content = controller._build_docx_from_text(
            html,
            lor_styles=controller._default_lor_docx_styles(),
        )

        with ZipFile(BytesIO(docx_content)) as archive:
            numbering_xml = archive.read('word/numbering.xml').decode('utf-8')
            document_xml = archive.read('word/document.xml').decode('utf-8')

        self.assertIn('<w:numFmt w:val="bullet"/>', numbering_xml)
        self.assertIn('<w:lvlText w:val="•"/>', numbering_xml)
        self.assertIn('<w:numId w:val="2"/>', document_xml)

    def test_lor_docx_uses_requested_page_setup_and_footer_numbering(self):
        controller = LorReportController()
        html = '<html><body><p>Body text</p></body></html>'

        docx_content = controller._build_docx_from_text(
            html,
            lor_styles=controller._parse_lor_css_styles(get_default_lor_css_source()),
        )

        with ZipFile(BytesIO(docx_content)) as archive:
            document_xml = archive.read('word/document.xml').decode('utf-8')
            footer_xml = archive.read('word/footer1.xml').decode('utf-8')
            rels_xml = archive.read('word/_rels/document.xml.rels').decode('utf-8')

        self.assertIn('w:orient="portrait"', document_xml)
        self.assertIn('w:top="1928"', document_xml)
        self.assertIn('w:right="1440"', document_xml)
        self.assertIn('w:bottom="850"', document_xml)
        self.assertIn('w:left="1440"', document_xml)
        self.assertIn('w:header="680"', document_xml)
        self.assertIn('w:footer="113"', document_xml)
        self.assertIn('footerReference', document_xml)
        self.assertIn('relationships/footer', rels_xml)
        self.assertIn(' PAGE ', footer_xml)
        self.assertIn('\\* MERGEFORMAT', footer_xml)
        self.assertIn('Page Numbers (Bottom of Page)', footer_xml)
        self.assertIn('<w:pStyle w:val="Footer"/>', footer_xml)
        self.assertNotIn(' NUMPAGES ', footer_xml)
        self.assertNotIn('Page ', footer_xml)
        self.assertNotIn(' of ', footer_xml)
        self.assertIn('w:fldCharType="begin" w:dirty="true"', footer_xml)
        self.assertNotIn('<w:pict>', footer_xml)
        self.assertNotIn('<v:rect', footer_xml)
        self.assertNotIn('<w:textAlignment w:val="bottom"/>', footer_xml)
        self.assertNotIn('<w:spacing w:before="0" w:after="0" w:line="180" w:lineRule="exact"/>', footer_xml)
        self.assertNotIn('<w:position w:val="-2"/>', footer_xml)
        self.assertNotIn('<w:position w:val="-8"/>', footer_xml)
        self.assertIn('<w:sz w:val="18"/>', footer_xml)

    def test_lor_docx_page_numbers_follow_explicit_page_number_typography_without_background(self):
        controller = LorReportController()
        html = '<html><body><p>Body text</p></body></html>'
        lor_styles = controller._default_lor_docx_styles()
        lor_styles['body']['font_family'] = 'Garamond'
        lor_styles['body']['font_size_half_points'] = 28
        lor_styles['document']['page_number_font_family'] = 'Calibri'
        lor_styles['document']['page_number_font_size_half_points'] = 40

        docx_content = controller._build_docx_from_text(
            html,
            lor_styles=lor_styles,
        )

        with ZipFile(BytesIO(docx_content)) as archive:
            footer_xml = archive.read('word/footer1.xml').decode('utf-8')

        self.assertIn('w:ascii="Calibri"', footer_xml)
        self.assertIn('<w:sz w:val="40"/>', footer_xml)
        self.assertIn('<w:highlight w:val="none"/>', footer_xml)
        self.assertIn('<w:shd w:val="nil"/>', footer_xml)
        self.assertIn('\\* MERGEFORMAT', footer_xml)
        self.assertIn('<w:pStyle w:val="Footer"/>', footer_xml)
        self.assertNotIn(' NUMPAGES ', footer_xml)
        self.assertNotIn('Page ', footer_xml)
        self.assertNotIn(' of ', footer_xml)
        self.assertNotIn('<w:pict>', footer_xml)
        self.assertNotIn('<v:rect', footer_xml)
        self.assertNotIn('<w:textAlignment w:val="bottom"/>', footer_xml)
        self.assertNotIn('<w:spacing w:before="0" w:after="0" w:line="400" w:lineRule="exact"/>', footer_xml)
        self.assertNotIn('<w:position w:val="-8"/>', footer_xml)
        self.assertNotIn('Garamond', footer_xml)

    def test_lor_docx_paragraph_spacing_defaults_to_zero_before_and_after(self):
        controller = LorReportController()
        html = (
            '<html><body>'
            '<h1 class="title">Title</h1>'
            '<p class="salutation">Dear Sirs</p>'
            '<p class="intro">Intro text</p>'
            '<ol class="list-level-0"><li>List item</li></ol>'
            '<p class="closing">Closing text</p>'
            '</body></html>'
        )

        docx_content = controller._build_docx_from_text(
            html,
            lor_styles=controller._parse_lor_css_styles(get_default_lor_css_source()),
        )

        with ZipFile(BytesIO(docx_content)) as archive:
            document_xml = archive.read('word/document.xml').decode('utf-8')

        spacing_values = re.findall(
            r'<w:spacing\b[^>]*w:before="(\d+)"[^>]*w:after="(\d+)"[^>]*/>',
            document_xml,
        )

        self.assertTrue(spacing_values)
        self.assertTrue(all(before == '0' and after == '0' for before, after in spacing_values))

    def test_lor_gap_class_and_last_nested_list_item_add_twelve_point_spacing(self):
        controller = LorReportController()
        html = (
            '<html><body>'
            '<p class="intro gap">Intro text</p>'
            '<ol class="list-level-0 gap">'
            '<li>Parent item'
            '<ol class="list-level-1"><li>Child item 1</li><li class="gap">Child item 2</li></ol>'
            '</li>'
            '</ol>'
            '<p class="gap">Gap paragraph</p>'
            '</body></html>'
        )

        blocks = controller._extract_lor_blocks_from_html(html)
        self.assertEqual(blocks[0]['gap_after_twips'], 240)
        self.assertEqual(blocks[1]['gap_after_twips'], 240)
        self.assertEqual(blocks[2]['gap_after_twips'], 0)
        self.assertEqual(blocks[3]['gap_after_twips'], 240)
        self.assertEqual(blocks[4]['gap_after_twips'], 240)

        docx_content = controller._build_docx_from_text(
            html,
            lor_styles=controller._parse_lor_css_styles(get_default_lor_css_source()),
        )

        with ZipFile(BytesIO(docx_content)) as archive:
            document_xml = archive.read('word/document.xml').decode('utf-8')

        spacing_values = re.findall(
            r'<w:spacing\b[^>]*w:before="(\d+)"[^>]*w:after="(\d+)"[^>]*/>',
            document_xml,
        )
        self.assertEqual(
            spacing_values[:5],
            [('0', '240'), ('0', '240'), ('0', '0'), ('0', '240'), ('0', '240')],
        )

    def test_lor_docx_br_tag_renders_as_word_line_break(self):
        controller = LorReportController()
        html = '<html><body><p>First line<br/>Second line</p></body></html>'

        docx_content = controller._build_docx_from_text(
            html,
            lor_styles=controller._parse_lor_css_styles(get_default_lor_css_source()),
        )

        with ZipFile(BytesIO(docx_content)) as archive:
            document_xml = archive.read('word/document.xml').decode('utf-8')

        self.assertIn('First line', document_xml)
        self.assertIn('Second line', document_xml)
        self.assertIn('<w:br/>', document_xml)

    def test_lor_html_br_between_paragraphs_becomes_blank_line_block(self):
        controller = LorReportController()
        blocks = controller._extract_lor_blocks_from_html(
            '<html><body><p>First</p><br/><p>Second</p></body></html>'
        )

        self.assertEqual(len(blocks), 3)
        self.assertEqual(blocks[1]['style_key'], 'spacer_line')
        self.assertEqual(blocks[1]['text'], '')
        self.assertTrue(blocks[1]['preserve_empty'])

    def test_post_init_hook_updates_companies_using_previous_default_css(self):
        company = self.env['res.company'].create({'name': 'Legacy CSS Co'})
        previous_default_css = 'PREVIOUS_DEFAULT_LOR_CSS'
        company.write({'lor_template_css_source': previous_default_css})

        original_hash = res_company_model._hash_template_source

        def fake_hash(text_value):
            if text_value == previous_default_css:
                return 'e9158355a08c9a13556005badfcfe9386887ccb65b01659acd3b48500c815a2e'
            return original_hash(text_value)

        with patch.object(res_company_model, '_hash_template_source', side_effect=fake_hash):
            post_init_hook(self.env)

        company.invalidate_recordset(['lor_template_css_source'])
        self.assertEqual(company.lor_template_css_source, get_default_lor_css_source())
