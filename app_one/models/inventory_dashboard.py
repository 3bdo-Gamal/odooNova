from odoo import models, fields, api


class InventoryDashboard(models.Model):
    _name = 'wb.inventory.dashboard'
    _description = 'Inventory KPI Dashboard'

    name = fields.Char(default="Inventory Dashboard")
    currency_id = fields.Many2one(
        'res.currency',
        default=lambda self: self.env.company.currency_id
    )

    total_products = fields.Integer(string="Total Products", compute="_compute_inventory_kpis")
    stock_value_field = fields.Monetary(string="Stock Value", compute="_compute_inventory_kpis",
                                        currency_field='currency_id')
    low_stock_count = fields.Integer(string="Low Stock Items", compute="_compute_inventory_kpis")

    def _compute_inventory_kpis(self):
        products = self.env['product.product'].search([('detailed_type', '=', 'product')])
        for record in self:
            record.total_products = len(products)
            record.stock_value_field = sum(p.qty_available * p.standard_price for p in products)
            record.low_stock_count = len(products.filtered(lambda p: p.qty_available < 5))

    # الـ Method اللي كانت ناقصة ومسببة الـ RPC_ERROR
    @api.model
    def get_inventory_kpis(self, filters=None):
        if filters is None:
            filters = {}

        products = self.env['product.product'].search([('detailed_type', '=', 'product')])
        stock_value = sum(p.qty_available * p.standard_price for p in products)

        # حسابات تجريبية للـ Dashboard
        return {
            'stock_on_hand': sum(p.qty_available for p in products),
            'stock_value': stock_value,
            'low_stock_count': len(products.filtered(lambda p: p.qty_available < 10)),
            'inventory_turnover': 1.2,  # تقدري تحسبيها فعلياً لاحقاً
            'dio': 45.5,
            'abc_data': {
                'labels': ['Category A', 'Category B', 'Category C'],
                'data': [70, 20, 10]
            }
        }

    @api.model
    def create_dashboard_record(self):
        if not self.search([], limit=1):
            self.create({})