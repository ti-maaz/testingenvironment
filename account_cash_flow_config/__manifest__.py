{
    'name': 'Account Cash Flow Config',
    'version': '1.0',
    'category': 'Accounting',
    'summary': 'Configuration for Account Cash Flow Reporting',
    'description': """
        This module provides configuration options for managing account cash flow reports.
    """,
    'author': 'TI Associates',
    'depends': ['account'],
    'data': [
        'views/account_account_view.xml',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}

