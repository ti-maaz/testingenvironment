{
    'name': 'Customer Invoice Serial Check',
    'version': '19.0.1.0.0',
    'summary': 'Check missing posted customer invoice serial numbers',
    'category': 'Accounting/Accounting',
    'license': 'LGPL-3',
    'depends': ['account'],
    'data': [
        'views/account_move_views.xml',
    ],
    'installable': True,
    'application': False,
}
