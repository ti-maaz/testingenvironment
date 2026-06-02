import logging

from odoo import api, models

_logger = logging.getLogger(__name__)

DEFAULT_LAYOUT_KEY = 'document_layout_defaults.external_layout_custom'
DEFAULT_BACKGROUND = 'Demo logo'


class ResCompany(models.Model):
    _inherit = 'res.company'

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _build_default_footer(self):
        """Build a sensible HTML footer from the company's own fields."""
        self.ensure_one()
        parts = [self.name]
        if self.phone:
            parts.append(f"Tel: {self.phone}")
        if self.email:
            parts.append(self.email)
        if self.website:
            parts.append(self.website)
        return '<p>' + ' | '.join(parts) + '</p>'

    def _apply_document_layout_defaults(self):
        """
        Apply document layout defaults to companies that have not been
        configured yet (layout_background still 'Blank' and no layout set).

        Safe to call multiple times — already-configured companies are skipped.
        """
        layout_view = self.env['ir.ui.view'].search(
            [('key', '=', DEFAULT_LAYOUT_KEY)], limit=1
        )
        if not layout_view:
            _logger.warning(
                "document_layout_defaults: layout view '%s' not found — skipping.",
                DEFAULT_LAYOUT_KEY,
            )
            return

        for company in self:
            needs_layout = not company.external_report_layout_id
            needs_background = company.layout_background == 'Blank'
            needs_footer = not company.report_footer

            if not (needs_layout or needs_background or needs_footer):
                _logger.info(
                    "document_layout_defaults: company '%s' already configured — skipped.",
                    company.name,
                )
                continue

            vals = {}
            if needs_layout:
                vals['external_report_layout_id'] = layout_view.id
            if needs_background:
                vals['layout_background'] = DEFAULT_BACKGROUND
            if needs_footer:
                vals['report_footer'] = company._build_default_footer()

            company.write(vals)
            _logger.info(
                "document_layout_defaults: configured company '%s' — layout=%s, background=%s, footer_set=%s.",
                company.name,
                needs_layout,
                needs_background,
                needs_footer,
            )

    # ------------------------------------------------------------------
    # Auto-configure new companies on creation
    # ------------------------------------------------------------------

    @api.model_create_multi
    def create(self, vals_list):
        companies = super().create(vals_list)
        companies._apply_document_layout_defaults()
        return companies

    # ------------------------------------------------------------------
    # Server action entry point (called from the UI button)
    # ------------------------------------------------------------------

    def action_apply_layout_defaults_all(self):
        """Re-apply layout defaults to ALL companies (called from server action)."""
        all_companies = self.search([])
        # Temporarily clear layout_background so the helper re-applies it
        # only for companies whose background is still 'Blank'.
        all_companies._apply_document_layout_defaults()
        return {
            'type': 'ir.actions.client',
            'tag': 'display_notification',
            'params': {
                'title': 'Document Layout',
                'message': f'Layout defaults applied to {len(all_companies)} company(ies).',
                'type': 'success',
                'sticky': False,
            },
        }
