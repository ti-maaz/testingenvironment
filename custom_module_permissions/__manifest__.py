{
    'name': 'Custom Module Permissions',
    'version': '19.0.1.0.1',
    'summary': 'Unified per-user permission framework for custom modules',
    'description': """
        Unified permission category + Users form controls for custom module access.
        Includes visibility controls for Audit Report, Audit Excel Export,
        Bank Transaction Recode,
        and CoA restrictions.
    """,
    'author': 'TI Associates',
    'license': 'LGPL-3',
    'category': 'Tools',
    'depends': [
        'base',
        'web',
        'account',
        'account_move_bulk_reset_to_draft',
        'Audit_Report',
        'audit_excel_export',
    ],
    'data': [
        'security/custom_module_permission_groups.xml',
        'security/ir.model.access.csv',
        'views/module_visibility_views.xml',
        'views/res_users_views.xml',
    ],
    'post_init_hook': 'post_init_hook',
    'installable': True,
    'application': False,
}
