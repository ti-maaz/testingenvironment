{
    'name': 'Bank Transaction VAT Excel Export',
    'version': '19.0.1.0.0',
    'summary': 'Export bank transactions to a "VAT Working" Excel format.',
    'category': 'Accounting',
    'author': 'TI Associates',
    'license': 'LGPL-3',
    'depends': [
        'account',
        'vat_audit_excel_pack',
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/account_bank_statement_line_views.xml',
        'wizard/bank_transaction_vat_export_wizard_views.xml',
    ],
    'installable': True,
    'application': False,
}
