from odoo import models, fields, api
from datetime import timedelta


class InventoryDashboard(models.Model):
    _name = 'wb.inventory.dashboard'
    _description = 'Professional Inventory KPI Dashboard'

    name = fields.Char(default="Inventory Dashboard")
    currency_id = fields.Many2one('res.currency', default=lambda self: self.env.company.currency_id)

    @api.model
    def get_inventory_kpis(self, filters=None):
        if filters is None: filters = {}

        # تجهيز النطاقات (Domains) بناءً على الفلاتر
        product_domain = [('detailed_type', '=', 'product')]
        quant_domain = [('location_id.usage', '=', 'internal')]

        if filters.get('product_id'):
            product_domain.append(('id', '=', int(filters['product_id'])))
            quant_domain.append(('product_id', '=', int(filters['product_id'])))

        if filters.get('warehouse_id'):
            warehouse = self.env['stock.warehouse'].browse(int(filters['warehouse_id']))
            quant_domain.append(('location_id', 'child_of', warehouse.view_location_id.id))

        # جلب البيانات الأساسية
        products = self.env['product.product'].search(product_domain)
        quants = self.env['stock.quant'].search(quant_domain)

        # 1. Stock On Hand المفلتر
        stock_on_hand = sum(quants.mapped('quantity'))

        # 2. إجمالي القيمة (Ending Inventory)
        ending_stock_value = sum(p.qty_available * p.standard_price for p in products)

        # 3. حساب COGS (تكلفة البضاعة المباعة)
        date_from = fields.Date.today() - timedelta(days=365)
        out_moves_domain = [('state', '=', 'done'), ('location_dest_id.usage', '=', 'customer'),
                            ('date', '>=', date_from)]
        if filters.get('product_id'):
            out_moves_domain.append(('product_id', '=', int(filters['product_id'])))

        out_moves = self.env['stock.move'].search(out_moves_domain)
        cogs = sum(move.product_uom_qty * (move.price_unit or move.product_id.standard_price) for move in out_moves)

        # 4. الحسابات الاحترافية (Turnover & DIO)
        inventory_turnover = round(cogs / (ending_stock_value or 1), 3)
        dio = round(min(365 / (inventory_turnover or 0.001), 365), 1) if inventory_turnover > 0 else 0

        return {
            'stock_on_hand': stock_on_hand,
            'stock_value': ending_stock_value,
            'inventory_turnover': f"{inventory_turnover}x",
            'dio': f"{int(dio)} Days" if dio > 0 else "0 Days",
            'low_stock_count': len(products.filtered(lambda p: p.qty_available <= p.reordering_min_qty)),
            'warehouses': self.env['stock.warehouse'].search_read([], ['id', 'name']),
            'products_list': self.env['product.product'].search_read([('detailed_type', '=', 'product')],
                                                                     ['id', 'display_name']),
            'abc_data': {
                'labels': [cat.name for cat in self.env['product.category'].search([]) if
                           products.filtered(lambda p: p.categ_id == cat)],
                'data': [sum(p.qty_available * p.standard_price for p in products.filtered(lambda p: p.categ_id == cat))
                         for cat in self.env['product.category'].search([]) if
                         products.filtered(lambda p: p.categ_id == cat)]
            }
        }