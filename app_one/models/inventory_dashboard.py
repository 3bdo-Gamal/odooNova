
from odoo import models, fields, api


class InventoryDashboard(models.Model):
    _name = 'wb.inventory.dashboard'
    _description = 'Inventory KPI Dashboard'

    name = fields.Char(default="Inventory Dashboard")
    currency_id = fields.Many2one('res.currency', default=lambda self: self.env.company.currency_id)


    total_products = fields.Integer(string="Total Products", compute="_compute_inventory_kpis")

    stock_value = fields.Monetary(string="Stock Value", compute="_compute_inventory_kpis")


    low_stock_count = fields.Integer(string="Low Stock Items", compute="_compute_inventory_kpis")

    def _compute_inventory_kpis(self):
        for record in self:

            products = self.env['product.product'].search([('detailed_type', '=', 'product')])

            record.total_products = len(products)


            record.stock_value = sum(p.qty_available * p.standard_price for p in products)


            low_stock_items = products.filtered(lambda p: p.qty_available < p.ROP)
            record.low_stock_count = len(low_stock_items)