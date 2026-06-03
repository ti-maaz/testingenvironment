{
    'name': 'Liquidation Report',
    'version': '19.0.1.0.0',
    'category': 'Accounting',
    'summary': 'Generate IFZA and free zone liquidation DOCX reports',
    'description': """
        Adds a dedicated liquidation report wizard backed by DOCX templates.
        The wizard can be launched standalone or from the Audit Report wizard.
    """,
    'author': 'Your Company',
    'license': 'LGPL-3',
    'depends': [
        'Audit_Report',
        'company_exte',
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/audit_report_views.xml',
        'views/liquidation_report_views.xml',
    ],
    'demo': [],
    'installable': True,
    'auto_install': False,
    'application': False,
}
