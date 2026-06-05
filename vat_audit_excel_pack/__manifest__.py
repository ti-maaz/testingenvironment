{
    'name': 'VAT Audit Excel Pack',
    'version': '19.0.1.0.0',
    'category': 'Accounting',
    'summary': 'Generate a multi-sheet VAT and audit support Excel workbook',
    'description': """
        Adds an accounting wizard to generate a single Excel workbook with:
        - General Ledger
        - Trial Balance
        - Profit and Loss
        - Balance Sheet
        - Aged Receivable
        - Aged Payable
        - Sale
        - Purchases
        - Not Claimable
    """,
    'author': 'TI Associates',
    'license': 'LGPL-3',
    'depends': [
        'account',
        'account_reports',
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/vat_audit_excel_pack_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
