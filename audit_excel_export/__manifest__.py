{
    'name': 'Audit Excel Export',
    'version': '19.0.1.0.0',
    'category': 'Accounting',
    'summary': 'Generate a multi-sheet audit Excel workbook from accounting data',
    'description': """
        Adds an Accounting wizard to export General Ledger, Customer Invoices,
        Vendor Bills, Aged Receivables, and Aged Payables to one custom XLSX file.
    """,
    'author': 'TI Associates',
    'license': 'LGPL-3',
    'depends': [
        'account',
        'account_reports',
        'Audit_Report',
    ],
    'external_dependencies': {
        'python': ['openpyxl'],
    },
    'data': [
        'security/ir.model.access.csv',
        'data/audit_invoice_bill_reports.xml',
        'views/audit_excel_export_views.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
