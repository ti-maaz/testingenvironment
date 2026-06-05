from odoo import Command, api, fields, models


class ResUsers(models.Model):
    _inherit = 'res.users'

    allow_debug_mode = fields.Boolean(
        string='Allow Debug Mode',
        default=False,
        help='If enabled, this user can activate developer mode from URL debug parameters.',
    )

    @api.model
    def _custom_module_group_domain(self):
        category = self.env.ref(
            'custom_module_permissions.module_category_custom_module_access',
            raise_if_not_found=False,
        )
        if not category:
            return [('id', '=', False)]
        return [('privilege_id.category_id', '=', category.id)]

    @api.model
    def _domain_custom_module_group_ids(self):
        return self._custom_module_group_domain()

    custom_module_group_ids = fields.Many2many(
        'res.groups',
        string='Custom Module Permissions',
        compute='_compute_custom_module_group_ids',
        inverse='_inverse_custom_module_group_ids',
        domain=lambda self: self._domain_custom_module_group_ids(),
        help='Custom module visibility groups managed by administrators.',
    )

    @api.model
    def _get_custom_module_groups(self):
        return self.env['res.groups'].search(self._custom_module_group_domain())

    @api.depends('group_ids')
    def _compute_custom_module_group_ids(self):
        custom_groups = self._get_custom_module_groups()
        for user in self:
            user.custom_module_group_ids = user.group_ids & custom_groups

    def _inverse_custom_module_group_ids(self):
        custom_groups = self._get_custom_module_groups()
        for user in self:
            retained_non_custom_groups = user.group_ids - custom_groups
            selected_custom_groups = user.custom_module_group_ids & custom_groups
            user.group_ids = [Command.set((retained_non_custom_groups | selected_custom_groups).ids)]
