from odoo import models, fields

class ResCompany(models.Model):
    _inherit = 'res.company'

    # Free Zone & License
    free_zone = fields.Char(string="Company Free Zone")
    company_license_number = fields.Char(string="Company License Number")
    trade_license_activities = fields.Text(string="Trade License Activities")

    # Tax Information
    corporate_tax_registration_number = fields.Char(
        string="Corporate Tax Registration Number"
    )
    vat_registration_number = fields.Char(
        string="VAT Registration Number"
    )

    corporate_tax_start_date = fields.Date(
        string="Corporate Tax Start Date"
    )
    corporate_tax_end_date = fields.Date(
        string="Corporate Tax End Date"
    )

    # Incorporation
    incorporation_date = fields.Date(
        string="Company Incorporation Date"
    )

    # Regulations
    implementing_regulations_freezone = fields.Text(
        string="Implementing Regulations for Free Zones"
    )

    # Shareholders (Simple Char Field)
    shareholder_ids = fields.Char(
        string="Company Shareholders"
    )

    shareholders_nationalities = fields.Char(
        string="Nationality"
    )

    shareholder_1 = fields.Char()
    shareholder_2 = fields.Char()
    shareholder_3 = fields.Char()
    shareholder_4 = fields.Char()
    shareholder_5 = fields.Char()
    shareholder_6 = fields.Char()
    shareholder_7 = fields.Char()
    shareholder_8 = fields.Char()
    shareholder_9 = fields.Char()
    shareholder_10 = fields.Char()

    nationality_1 = fields.Char()
    nationality_2 = fields.Char()
    nationality_3 = fields.Char()
    nationality_4 = fields.Char()
    nationality_5 = fields.Char()
    nationality_6 = fields.Char()
    nationality_7 = fields.Char()
    nationality_8 = fields.Char()
    nationality_9 = fields.Char()
    nationality_10 = fields.Char()

