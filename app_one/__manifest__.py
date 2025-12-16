{
    'name': 'App One',
    'version': '1.0',
    'author': '3bdo',
'depends': ['base', 'sale', 'board'],

'data': [
    'security/ir.model.access.csv',
    'data/dashboard_data.xml',
"data/dashboard_inventory.xml",
    'views/app_one_view.xml',
    'views/dashboard_view.xml',
    "views/inventory_view.xml",

],


    'application': True,
}
