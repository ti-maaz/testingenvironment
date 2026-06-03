{
    'name': 'Account Report Display Currency',
    'version': '19.0.1.0.0',
    'summary': 'Display accounting reports in a selected presentation currency',
    'category': 'Accounting',
    'author': 'TI Associates',
    'license': 'LGPL-3',
    'depends': [
        'account_reports',
    ],
    'data': [],
    'assets': {
        'web.assets_backend': [
            'account_report_display_currency/static/src/js/account_report_filters_display_currency.js',
            'account_report_display_currency/static/src/xml/account_report_filters_display_currency.xml',
        ],
    },
    'installable': True,
    'application': False,
}
