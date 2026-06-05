from odoo import Command


POST_INIT_GROUP_XMLIDS = (
    'custom_module_permissions.group_custom_module_audit_report',
    'custom_module_permissions.group_custom_module_audit_excel_export',
    'custom_module_permissions.group_custom_module_account_bank_recode',
)

OPTIONAL_ACTION_GROUP_BINDINGS = (
    (
        'account_bank_recode.action_bank_statement_line_recode',
        'custom_module_permissions.group_custom_module_account_bank_recode',
    ),
    (
        'account_bank_recode.action_open_bank_recode_wizard',
        'custom_module_permissions.group_custom_module_account_bank_recode',
    ),
)


def _apply_optional_action_group_bindings(env):
    for action_xmlid, group_xmlid in OPTIONAL_ACTION_GROUP_BINDINGS:
        action = env.ref(action_xmlid, raise_if_not_found=False)
        group = env.ref(group_xmlid, raise_if_not_found=False)
        if not action or not group:
            continue
        action.write({'group_ids': [Command.set([group.id])]})


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

    _apply_optional_action_group_bindings(env)
