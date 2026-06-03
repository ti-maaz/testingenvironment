{
    'name': 'Company Other Information',
    'version': '1.0',
    'summary': 'Additional company legal, tax and free zone information',
    'category': 'Base',
    'depends': ['base'],
    'data': [
        # 'security/ir.model.access.csv',
        'views/res_company_view.xml',
        'views/res_company_shareholders.xml',
    ],
    'installable': True,
    'application': False,
}
