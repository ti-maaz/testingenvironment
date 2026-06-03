{
    'name': 'LOR Report',
    'version': '19.0.1.0.0',
    'category': 'Accounting',
    'summary': 'Company-backed Letter of Representation sources for audit reports',
    'description': """
        Adds a dedicated addon for Letter of Representation source management.
        Each company can maintain its own LOR HTML and CSS source, and audit
        report DOCX generation uses that company-specific source.
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
        'views/res_company_view.xml',
        'views/lor_report_views.xml',
    ],
    'post_init_hook': 'post_init_hook',
    'demo': [],
    'installable': True,
    'auto_install': False,
    'application': False,
}
