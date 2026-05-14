{
    'name': 'Odoo Nova',
    'version': '1.0',
    'author': '3bdo',
    'depends': [
        'base', 'sale', 'board', 'hr', 'hr_attendance',
        'project', 'hr_holidays', 'purchase', 'account',
        'purchase_requisition', 'point_of_sale'
    ],

    'data': [
        'security/ir.model.access.csv',
        'data/dashboard_inventory.xml',
        'views/app_one_view.xml',
        'views/sales_view.xml',
        'views/purchase_bills_view.xml',
        'views/inventory_view.xml',
        'views/hr_view.xml',
        'views/PO.xml',
        'views/bill_search.xml',
        'views/cashflow_view.xml',
    ],

    "assets": {
        "web.assets_backend": [
            # "app_one/static/lib/html2pdf.bundle.min.js"
            "app_one/static/src/js/bills_dashboard.js",
            "app_one/static/src/xml/bills_dashboard.xml",
            "app_one/static/src/js/dashboard.js",
            "app_one/static/src/xml/dashboard.xml",
            "app_one/static/src/js/po_dashboard.js",
            "app_one/static/src/xml/po_dashboard.xml",
            "app_one/static/src/js/inventory_dashboard.js",
            "app_one/static/src/xml/inventory_dashboard.xml",
            "app_one/static/src/js/Sales_dashboard.js",
            "app_one/static/src/xml/sales_dashboard.xml",
            "app_one/static/src/js/invoicing_dashboard.js",
            "app_one/static/src/xml/invoicing_dashboard.xml",
            "app_one/static/src/js/pos_dashboard.js",
            "app_one/static/src/xml/pos_dashboard.xml",
            "app_one/static/src/js/cashflow_dashboard.js",
            "app_one/static/src/xml/cashflow_dashboard.xml",
        ]
    },

    'application': True,
    'license': 'LGPL-3',
}