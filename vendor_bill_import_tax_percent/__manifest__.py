{
    'name': 'Vendor Bill Import Tax Percent',
    'version': '19.0.1.0.0',
    'category': 'Accounting/Accounting',
    'summary': 'Accept numeric percentage tax values in vendor bill imports',
    'description': """
        Normalizes percentage-like tax values on vendor bill import lines.

        Users can import purchase taxes on invoice lines as 5, 5%, or 0.05
        and the module maps the value to the matching active purchase tax for
        the bill company before Odoo computes VAT normally.
    """,
    'author': 'TI Associates',
    'license': 'LGPL-3',
    'depends': [
        'account',
        'base_import',
    ],
    'data': [],
    'installable': True,
    'application': False,
    'auto_install': False,
}
