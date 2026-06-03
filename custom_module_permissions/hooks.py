from odoo import Command


POST_INIT_GROUP_XMLIDS = (
    'custom_module_permissions.group_custom_module_audit_report',
    'custom_module_permissions.group_custom_module_audit_excel_export',
    'custom_module_permissions.group_custom_module_account_bank_recode',
)


def post_init_hook(env):
    internal_users = env['res.users'].with_context(active_test=False).search([
        ('share', '=', False),
    ])
    if not internal_users:
        return

    for xmlid in POST_INIT_GROUP_XMLIDS:
        group = env.ref(xmlid, raise_if_not_found=False)
        if not group:
            continue
        internal_users.write({'group_ids': [Command.link(group.id)]})
