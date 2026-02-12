{
    'name': 'odooNova',
    'version': '1.0',
    'author': '3bdo',
    'depends': ['base', 'sale', 'board', 'product', 'stock'],
    'data': [
        'security/ir.model.access.csv',
        'data/dashboard_sales.xml',
        'data/dashboard_inventory.xml',
        'data/dashboard_hr.xml',
        'views/app_one_view.xml',
        'views/sales_view.xml',
        'views/inventory_view.xml',
        'views/product_extension_view.xml',
        'views/hr_view.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'app_one/static/src/js/dashboard.js',
            'app_one/static/src/xml/dashboard.xml',
        ]
    },
    'application': True,
}