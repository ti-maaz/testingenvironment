{
    'name': 'Bank Transaction Recode',
    'version': '19.0.1.0.0',
    'summary': 'Bulk recode accounts or labels on bank transactions',
    'category': 'Accounting',
    'author': 'TI Associates',
    'license': 'LGPL-3',
    'depends': [
        'account_accountant',
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/bank_rec_widget_views.xml',
        'wizard/account_bank_recode_wizard_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'account_bank_recode/static/src/components/button_list_patch.js',
            'account_bank_recode/static/src/components/button_list_patch.xml',
        ],
    },
    'installable': True,
    'application': False,
}
