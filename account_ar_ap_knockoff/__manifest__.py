{
    'name': 'AR/AP Knock-Off & Contra Settlement',
    'version': '19.0.1.0.0',
    'summary': 'Settle customer receivables against vendor payables with audited journal entries.',
    'category': 'Accounting',
    'author': 'Custom',
    'license': 'LGPL-3',
    'depends': [
        'account',
        'mail',
    ],
    'data': [
        'security/account_knockoff_security.xml',
        'security/ir.model.access.csv',
        'data/ir_sequence_data.xml',
        'views/account_knockoff_settlement_views.xml',
    ],
    'installable': True,
    'application': False,
}
