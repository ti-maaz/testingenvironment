{
    'name': 'Company Hierarchy Converter',
    'version': '19.0.1.0.0',
    'category': 'Administration',
    'summary': 'Safely convert parent/branch company relationships',
    'depends': ['base', 'account', 'mail'],
    'data': [
        'security/security.xml',
        'security/ir.model.access.csv',
        'views/company_hierarchy_audit_views.xml',
        'views/company_hierarchy_converter_views.xml',
        'views/menus.xml',
    ],
    'license': 'LGPL-3',
    'application': False,
    'installable': True,
}
