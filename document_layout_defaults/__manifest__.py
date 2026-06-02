{
    'name': 'Document Layout Defaults',
    'version': '19.0.1.0.0',
    'summary': 'Automatically configures document layout (logo, background, footer) for all companies',
    'category': 'Technical',
    'author': 'Custom',
    'depends': ['web', 'base_setup'],
    'data': [
        'data/server_action.xml',
    ],
    'post_init_hook': 'post_init_hook',
    'auto_install': False,
    'installable': True,
    'license': 'LGPL-3',
}
