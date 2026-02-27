from odoo import models, fields, api
from datetime import timedelta


class InventoryDashboard(models.Model):
    _name = 'wb.inventory.dashboard'
    _description = 'Professional Inventory KPI Dashboard'

    name = fields.Char(default="Inventory Dashboard")

    @api.model
    def get_inventory_kpis(self, filters=None):
        if filters is None: filters = {}

        # تجهيز النطاقات (Domains)
        product_domain = [('detailed_type', '=', 'product')]
        quant_domain = [('location_id.usage', '=', 'internal')]
        move_domain = [('state', '=', 'done'), ('location_dest_id.usage', '=', 'customer')]

        # تطبيق فلاتر المنتج والمخزن
        if filters.get('product_id'):
            p_id = int(filters['product_id'])
            product_domain.append(('id', '=', p_id))
            quant_domain.append(('product_id', '=', p_id))
            move_domain.append(('product_id', '=', p_id))

        if filters.get('warehouse_id'):
            warehouse = self.env['stock.warehouse'].browse(int(filters['warehouse_id']))
            quant_domain.append(('location_id', 'child_of', warehouse.view_location_id.id))
            move_domain.append(('warehouse_id', '=', int(filters['warehouse_id'])))

        # تطبيق فلاتر التاريخ (تؤثر على الحركات المالية COGS فقط)
        if filters.get('date_from'):
            move_domain.append(('date', '>=', filters['date_from']))
        if filters.get('date_to'):
            move_domain.append(('date', '<=', filters['date_to']))

        # جلب البيانات
        products = self.env['product.product'].search(product_domain)
        quants = self.env['stock.quant'].search(quant_domain)
        out_moves = self.env['stock.move'].search(move_domain)

        # 1. Stock On Hand
        stock_on_hand = sum(quants.mapped('quantity'))

        # 2. Total Value
        ending_stock_value = sum(p.qty_available * p.standard_price for p in products)

        # 3. COGS
        cogs = sum(move.product_uom_qty * (move.price_unit or move.product_id.standard_price) for move in out_moves)

        # 4. Turnover & DIO
        inventory_turnover = round(cogs / (ending_stock_value or 1), 3)
        dio = round(min(365 / (inventory_turnover or 0.001), 365), 1) if inventory_turnover > 0 else 0

        # حساب Low Stock (المنتجات التي رصيدها أقل من حد إعادة الطلب)
        low_stock_products = products.filtered(lambda p: p.qty_available <= p.reordering_min_qty)

        return {
            'stock_on_hand': stock_on_hand,
            'stock_value': "{:,.2f}".format(ending_stock_value),
            'inventory_turnover': f"{inventory_turnover}x",
            'dio': f"{int(dio)} Days",
            'low_stock_count': len(low_stock_products),
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