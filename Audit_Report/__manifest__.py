{
    'name': 'Audit Report',
    'version': '19.0.1.0.2',
    'category': 'Accounting',
    'summary': 'Generate, edit, and store audit report revisions by company',
    'description': """
        This module provides a wizard to generate audit reports and manage
        saved, versioned, company-scoped report revisions.
    """,
    'author': 'TI Associates',
    'license': 'LGPL-3',
    'depends': [
        'account_reports',
        'account_accountant',
    ],
    'data': [
        'security/ir.model.access.csv',
        'security/audit_report_security.xml',
        'views/views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'Audit_Report/static/src/components/audit_tb_browser/**/*',
            'Audit_Report/static/src/scss/trial_balance_overrides.scss',
        ],
    },
    'demo': [],
    'installable': True,
    'auto_install': False,
    'application': False,
}
