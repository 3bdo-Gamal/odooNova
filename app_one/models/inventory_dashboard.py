from odoo import models, fields, api
from datetime import datetime, timedelta
import io
import base64

try:
    import xlsxwriter
except ImportError:
    xlsxwriter = None

class InventoryDashboard(models.Model):
    _name = 'wb.inventory.dashboard'
    _description = 'Professional Inventory KPI Dashboard'

    name = fields.Char(default="Inventory Dashboard")

    @api.model
    def get_filter_options(self):
        return {
            'warehouses': self.env['stock.warehouse'].search_read([], ['id', 'name']),
            'products': self.env['product.product'].search_read(
                [('detailed_type', '=', 'product')], ['id', 'display_name'], limit=200
            ),
            'categories': self.env['product.category'].search_read([], ['id', 'name']),
            'locations': self.env['stock.location'].search_read(
                [('usage', '=', 'internal')], ['id', 'complete_name']
            ),
        }

    def _build_domains(self, period, date_from, date_to,
                       warehouse_id, product_id, category_id, location_id):
        today = datetime.now()

        if date_from and date_to:
            dt_from = fields.Datetime.to_datetime(date_from)
            dt_to = fields.Datetime.to_datetime(date_to).replace(hour=23, minute=59, second=59)
        else:
            try:
                period = int(period)
            except Exception:
                period = 30
            dt_to = today
            dt_from = today - timedelta(days=period)

        days_count = max((dt_to - dt_from).days + 1, 1)

        product_domain = [('detailed_type', '=', 'product')]
        quant_domain = [('location_id.usage', '=', 'internal')]

        # Out: customer deliveries only
        move_out_domain = [
            ('state', '=', 'done'),
            ('location_id.usage', '=', 'internal'),
            ('location_dest_id.usage', '=', 'customer'),
            ('date', '>=', dt_from),
            ('date', '<=', dt_to),
        ]

        # In: supplier receipts only
        move_in_domain = [
            ('state', '=', 'done'),
            ('location_id.usage', '=', 'supplier'),
            ('location_dest_id.usage', '=', 'internal'),
            ('date', '>=', dt_from),
            ('date', '<=', dt_to),
        ]

        if product_id and product_id != 'all':
            pid = int(product_id)
            product_domain.append(('id', '=', pid))
            quant_domain.append(('product_id', '=', pid))
            move_out_domain.append(('product_id', '=', pid))
            move_in_domain.append(('product_id', '=', pid))

        if category_id and category_id != 'all':
            cid = int(category_id)
            product_domain.append(('categ_id', 'child_of', cid))
            quant_domain.append(('product_id.categ_id', 'child_of', cid))
            move_out_domain.append(('product_id.categ_id', 'child_of', cid))
            move_in_domain.append(('product_id.categ_id', 'child_of', cid))

        if warehouse_id and warehouse_id != 'all':
            wh = self.env['stock.warehouse'].browse(int(warehouse_id))
            quant_domain.append(('location_id', 'child_of', wh.view_location_id.id))
            move_out_domain.append(('warehouse_id', '=', int(warehouse_id)))
            move_in_domain.append(('picking_type_id.warehouse_id', '=', int(warehouse_id)))

        if location_id and location_id != 'all':
            quant_domain.append(('location_id', '=', int(location_id)))

        return (dt_from, dt_to, days_count,
                product_domain, quant_domain, move_out_domain, move_in_domain)

    @api.model
    def get_inventory_kpis(self, period=30, date_from=False, date_to=False,
                           warehouse_id='all', product_id='all',
                           category_id='all', location_id='all',
                           top_products=10, top_locations=10, top_categories=10,
                           dead_stock_days=90): # <-- Added parameter

        try: top_products = int(top_products)
        except Exception: top_products = 10
        try: top_locations = int(top_locations)
        except Exception: top_locations = 10
        try: top_categories = int(top_categories)
        except Exception: top_categories = 10
        try: dead_stock_days = int(dead_stock_days) # <-- Safe casting
        except Exception: dead_stock_days = 90

        (dt_from, dt_to, days_count,
         product_domain, quant_domain,
         move_out_domain, move_in_domain) = self._build_domains(
            period, date_from, date_to,
            warehouse_id, product_id, category_id, location_id
        )

        p_ctx = {}
        if warehouse_id != 'all': p_ctx['warehouse'] = int(warehouse_id)
        if location_id != 'all': p_ctx['location'] = int(location_id)

        products = self.env['product.product'].with_context(**p_ctx).search(product_domain)
        quants = self.env['stock.quant'].search(quant_domain)
        out_moves = self.env['stock.move'].search(move_out_domain)
        in_moves = self.env['stock.move'].search(move_in_domain)

        # Valuation Layers
        vl_out = self.env['stock.valuation.layer'].search([('stock_move_id', 'in', out_moves.ids)])
        out_val_map = {}
        for v in vl_out:
            out_val_map[v.stock_move_id.id] = out_val_map.get(v.stock_move_id.id, 0.0) + abs(v.value)

        vl_in = self.env['stock.valuation.layer'].search([('stock_move_id', 'in', in_moves.ids)])
        in_val_map = {}
        for v in vl_in:
            in_val_map[v.stock_move_id.id] = in_val_map.get(v.stock_move_id.id, 0.0) + v.value

        stock_on_hand = 0.0
        ending_stock_value = 0.0
        cat_data = {}
        product_value_map = {}
        location_stock = {}

        for q in quants:
            free_qty = max(q.quantity - q.reserved_quantity, 0.0)
            val = q.value if q.value else (q.quantity * q.product_id.standard_price)

            pid = q.product_id.id
            p_name = q.product_id.display_name or 'Unknown'
            c_name = q.product_id.categ_id.name or 'Unknown'
            loc_name = q.location_id.complete_name or q.location_id.name or 'Unknown'

            stock_on_hand += free_qty
            ending_stock_value += val
            cat_data[c_name] = cat_data.get(c_name, 0.0) + val
            location_stock[loc_name] = location_stock.get(loc_name, 0.0) + free_qty

            if pid not in product_value_map:
                product_value_map[pid] = {'name': p_name, 'value': 0.0}
            product_value_map[pid]['value'] += val

        cogs = 0.0
        received_value = 0.0
        daily_in, daily_out = {}, {}
        product_out = {}

        for i in range(days_count):
            key = (dt_from + timedelta(days=i)).strftime('%Y-%m-%d')
            daily_in[key] = daily_out[key] = 0.0

        for m in in_moves:
            k = m.date.strftime('%Y-%m-%d')
            if k in daily_in: daily_in[k] += m.quantity

            m_val = in_val_map.get(m.id, 0.0)
            if m_val == 0.0: m_val = m.quantity * m.product_id.standard_price
            received_value += m_val

        for m in out_moves:
            k = m.date.strftime('%Y-%m-%d')
            if k in daily_out: daily_out[k] += m.quantity

            m_val = out_val_map.get(m.id, 0.0)
            if m_val == 0.0: m_val = m.quantity * m.product_id.standard_price
            cogs += m_val

            p_name = m.product_id.display_name or 'Unknown'
            product_out[p_name] = product_out.get(p_name, 0.0) + m.quantity

        # --- FIX: Average Inventory Value Calculation ---
        # Beginning = Ending - Received + COGS (Fast Approximation)
        beginning_stock_value = ending_stock_value - received_value + cogs
        avg_inventory_value = (beginning_stock_value + ending_stock_value) / 2.0

        if avg_inventory_value > 0 and cogs > 0:
            inventory_turnover = round((cogs / avg_inventory_value) * (365.0 / days_count), 2)
            dio = round((avg_inventory_value / cogs) * days_count, 1)
        else:
            inventory_turnover = 0.0
            dio = 0.0
        # ------------------------------------------------

        op_domain = []
        if warehouse_id != 'all': op_domain.append(('warehouse_id', '=', int(warehouse_id)))

        orderpoints = self.env['stock.warehouse.orderpoint'].search(op_domain)
        reorder_min_map = {}
        for op in orderpoints:
            pid = op.product_id.id
            reorder_min_map[pid] = max(reorder_min_map.get(pid, 0.0), op.product_min_qty)

        # --- FIX: Low Stock uses virtual_available (Forecasted) ---
        low_stock_count = sum(1 for p in products if p.virtual_available <= reorder_min_map.get(p.id, 0.0))
        # ----------------------------------------------------------

        # --- FIX: Dynamic Dead Stock Days ---
        if products:
            dead_cutoff = datetime.now() - timedelta(days=dead_stock_days)
            dead_base_domain = [('state', '=', 'done'), ('date', '>=', dead_cutoff), ('product_id', 'in', products.ids)]

            dead_out_ids = set(self.env['stock.move'].search(dead_base_domain + [
                ('location_id.usage', '=', 'internal'), ('location_dest_id.usage', '=', 'customer')
            ]).mapped('product_id').ids)
            dead_in_ids = set(self.env['stock.move'].search(dead_base_domain + [
                ('location_id.usage', '=', 'supplier'), ('location_dest_id.usage', '=', 'internal')
            ]).mapped('product_id').ids)

            recently_moved_ids = dead_out_ids | dead_in_ids
            dead_stock_count = len([p for p in products if p.id not in recently_moved_ids and p.qty_available > 0])
        else:
            dead_stock_count = 0
        # ------------------------------------

        sorted_products = sorted(product_out.items(), key=lambda x: x[1], reverse=True)[:top_products]
        sorted_locations = sorted(location_stock.items(), key=lambda x: x[1], reverse=True)[:top_locations]
        sorted_categories = sorted(cat_data.items(), key=lambda x: x[1], reverse=True)[:top_categories]
        sorted_by_value = sorted(product_value_map.values(), key=lambda x: x['value'], reverse=True)

        total_stock_value = sum(x['value'] for x in sorted_by_value) or 1.0
        cumulative = 0.0
        abc = {'A': [], 'B': [], 'C': []}

        for x in sorted_by_value:
            cumulative += x['value'] / total_stock_value
            if cumulative <= 0.80: abc['A'].append(x['name'])
            elif cumulative <= 0.95: abc['B'].append(x['name'])
            else: abc['C'].append(x['name'])

        return {
            'stock_on_hand': round(stock_on_hand, 2),
            'stock_value': round(ending_stock_value, 2),
            'stock_value_fmt': "{:,.2f}".format(ending_stock_value),
            'cogs': round(cogs, 2),
            'cogs_fmt': "{:,.2f}".format(cogs),
            'received_value': round(received_value, 2),
            'received_value_fmt': "{:,.2f}".format(received_value),
            'inventory_turnover': f"{inventory_turnover}x",
            'dio': f"{int(dio)} Days",
            'low_stock_count': low_stock_count,
            'dead_stock_count': dead_stock_count,
            'dead_stock_threshold_days': dead_stock_days,
            'total_products': len(products),
            'trend_labels': list(daily_in.keys()),
            'trend_in': list(daily_in.values()),
            'trend_out': list(daily_out.values()),
            'category_value_labels': [i[0] for i in sorted_categories],
            'category_value_data': [round(i[1], 2) for i in sorted_categories],
            'abc_class_a': abc['A'][:10],
            'abc_class_b': abc['B'][:10],
            'abc_class_c': abc['C'][:10],
            'top_product_labels': [i[0] for i in sorted_products],
            'top_product_data': [i[1] for i in sorted_products],
            'location_labels': [i[0] for i in sorted_locations],
            'location_data': [i[1] for i in sorted_locations],
        }

    @api.model
    def export_inventory_excel(self, period=30, date_from=False, date_to=False,
                               warehouse_id='all', product_id='all',
                               category_id='all', location_id='all',
                               export_group='product', export_measures=None, detailed_excel=False):
        # (This method remains functionally identical to your existing file, I've omitted it to save space, just keep your original export function here)
        pass