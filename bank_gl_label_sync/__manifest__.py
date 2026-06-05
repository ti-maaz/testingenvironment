{
    'name': 'Bank GL Label Sync',
    'version': '19.0.1.0.0',
    'summary': 'Sync bank transaction labels to General Ledger journal item labels',
    'category': 'Accounting',
    'author': 'TI Associates',
    'license': 'LGPL-3',
    'depends': [
        'account_accountant',
    ],
    'data': [
        'views/account_journal_views.xml',
    ],
    'installable': True,
    'application': False,
}
