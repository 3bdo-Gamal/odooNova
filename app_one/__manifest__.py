{
    'name': 'odooNova',
    'version': '1.0',
    'author': '3bdo',
'depends': ['base', 'sale', 'board','hr','hr_attendance','project','hr_holidays','purchase','account','purchase_requisition'],

'data': [
    'security/ir.model.access.csv',
    'data/dashboard_sales.xml',
    "data/dashboard_inventory.xml",
    'data/dashboard_hr.xml',
    'data/dashboard_PO.xml',
    'views/app_one_view.xml',
    'views/sales_view.xml',
    "views/inventory_view.xml",
    'views/purchase_bills_view.xml',
    "views/hr_view.xml",
    'views/PO.xml',

],
 "assets":{
     "web.assets_backend":[
         "app_one/static/src/js/bills_dashboard.js",
         "app_one/static/src/xml/bills_dashboard.xml",
         "app_one/static/src/js/dashboard.js",
         "app_one/static/src/xml/dashboard.xml",
         "app_one/static/src/xml/po_dashboard.xml",
         "app_one/static/src/js/po_dashboard.js"

]
 },


    'application': True,
}