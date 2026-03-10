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
        warehouses = self.env['stock.warehouse'].search_read([], ['id', 'name'])
        products = self.env['product.product'].search_read(
            [('detailed_type', '=', 'product')], ['id', 'display_name']
        )
        categories = self.env['product.category'].search_read([], ['id', 'name'])
        locations = self.env['stock.location'].search_read(
            [('usage', '=', 'internal')], ['id', 'complete_name']
        )
        return {
            'warehouses': warehouses,
            'products': products,
            'categories': categories,
            'locations': locations,
        }

    @api.model
    def get_inventory_kpis(
        self,
        period=30,
        date_from=False,
        date_to=False,
        warehouse_id='all',
        product_id='all',
        category_id='all',
        location_id='all',
    ):
        today = datetime.now()
        if date_from and date_to:
            dt_from = datetime.strptime(date_from, '%Y-%m-%d')
            dt_to = datetime.strptime(date_to, '%Y-%m-%d').replace(hour=23, minute=59, second=59)
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
        move_out_domain = [
            ('state', '=', 'done'),
            ('location_dest_id.usage', '=', 'customer'),
            ('date', '>=', dt_from),
            ('date', '<=', dt_to),
        ]
        move_in_domain = [
            ('state', '=', 'done'),
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

        products = self.env['product.product'].search(product_domain)
        quants = self.env['stock.quant'].search(quant_domain)
        out_moves = self.env['stock.move'].search(move_out_domain)
        in_moves = self.env['stock.move'].search(move_in_domain)

        stock_on_hand = sum(quants.mapped('quantity'))
        ending_stock_value = sum(
            q.quantity * (q.product_id.standard_price or 0.0) for q in quants
        )
        cogs = sum(
            m.product_uom_qty * (m.price_unit or m.product_id.standard_price or 0.0)
            for m in out_moves
        )
        received_value = sum(
            m.product_uom_qty * (m.price_unit or m.product_id.standard_price or 0.0)
            for m in in_moves
        )

        avg_inv = ending_stock_value or 1.0
        inventory_turnover = round(cogs / avg_inv, 3)
        dio = round(min(365.0 / (inventory_turnover or 0.001), 365.0), 1) if inventory_turnover > 0 else 0

        low_stock_products = self.env['product.product'].search([
            ('detailed_type', '=', 'product'),
            ('qty_available', '<=', 0),
        ])

        moved_ids = set(out_moves.mapped('product_id').ids) | set(in_moves.mapped('product_id').ids)
        dead_stock_products = products.filtered(
            lambda p: p.id not in moved_ids and p.qty_available > 0
        )

        daily_in = {}
        daily_out = {}
        for i in range(days_count):
            key = (dt_from + timedelta(days=i)).strftime('%Y-%m-%d')
            daily_in[key] = 0.0
            daily_out[key] = 0.0

        for m in in_moves:
            key = m.date.strftime('%Y-%m-%d')
            if key in daily_in:
                daily_in[key] += m.product_uom_qty

        for m in out_moves:
            key = m.date.strftime('%Y-%m-%d')
            if key in daily_out:
                daily_out[key] += m.product_uom_qty

        abc_labels = []
        abc_data = []
        for cat in self.env['product.category'].search([]):
            cat_quants = quants.filtered(lambda q: q.product_id.categ_id == cat)
            val = sum(q.quantity * (q.product_id.standard_price or 0.0) for q in cat_quants)
            if val > 0:
                abc_labels.append(cat.name)
                abc_data.append(round(val, 2))

        product_out = {}
        for m in out_moves:
            name = m.product_id.display_name or 'Unknown'
            product_out[name] = product_out.get(name, 0.0) + m.product_uom_qty
        sorted_products = sorted(product_out.items(), key=lambda x: x[1], reverse=True)[:10]

        location_stock = {}
        for q in quants:
            loc_name = q.location_id.complete_name or q.location_id.name or 'Unknown'
            location_stock[loc_name] = location_stock.get(loc_name, 0.0) + q.quantity
        sorted_locations = sorted(location_stock.items(), key=lambda x: x[1], reverse=True)[:10]

        return {
            'stock_on_hand': round(stock_on_hand, 2),
            'stock_value': round(ending_stock_value, 2),
            'stock_value_fmt': "{:,.2f}".format(ending_stock_value),
            'cogs': round(cogs, 2),
            'cogs_fmt': "{:,.2f}".format(cogs),
            'received_value': round(received_value, 2),
            'inventory_turnover': "{}x".format(inventory_turnover),
            'dio': "{} Days".format(int(dio)),
            'low_stock_count': len(low_stock_products),
            'dead_stock_count': len(dead_stock_products),
            'total_products': len(products),
            'trend_labels': list(daily_in.keys()),
            'trend_in': list(daily_in.values()),
            'trend_out': list(daily_out.values()),
            'abc_labels': abc_labels,
            'abc_data': abc_data,
            'top_product_labels': [i[0] for i in sorted_products],
            'top_product_data': [i[1] for i in sorted_products],
            'location_labels': [i[0] for i in sorted_locations],
            'location_data': [i[1] for i in sorted_locations],
        }

    @api.model
    def export_inventory_excel(
        self,
        period=30,
        date_from=False,
        date_to=False,
        warehouse_id='all',
        product_id='all',
        category_id='all',
        export_group='product',
        export_measures=None,
        detailed_excel=False,
    ):
        if export_measures is None:
            export_measures = ['qty', 'value']

        if not xlsxwriter:
            return False

        today = datetime.now()
        if date_from and date_to:
            dt_from = datetime.strptime(date_from, '%Y-%m-%d')
            dt_to = datetime.strptime(date_to, '%Y-%m-%d').replace(hour=23, minute=59, second=59)
        else:
            try:
                period = int(period)
            except Exception:
                period = 30
            dt_to = today
            dt_from = today - timedelta(days=period)

        quant_domain = [('location_id.usage', '=', 'internal')]
        move_out_domain = [
            ('state', '=', 'done'),
            ('location_dest_id.usage', '=', 'customer'),
            ('date', '>=', dt_from),
            ('date', '<=', dt_to),
        ]

        if product_id and product_id != 'all':
            pid = int(product_id)
            quant_domain.append(('product_id', '=', pid))
            move_out_domain.append(('product_id', '=', pid))

        if category_id and category_id != 'all':
            cid = int(category_id)
            quant_domain.append(('product_id.categ_id', 'child_of', cid))
            move_out_domain.append(('product_id.categ_id', 'child_of', cid))

        if warehouse_id and warehouse_id != 'all':
            wh = self.env['stock.warehouse'].browse(int(warehouse_id))
            quant_domain.append(('location_id', 'child_of', wh.view_location_id.id))
            move_out_domain.append(('warehouse_id', '=', int(warehouse_id)))

        quants = self.env['stock.quant'].search(quant_domain)
        out_moves = self.env['stock.move'].search(move_out_domain)

        pivot_data = {}

        if export_group == 'product':
            for q in quants:
                key = q.product_id.display_name or 'Unknown'
                if key not in pivot_data:
                    pivot_data[key] = {
                        'qty': 0.0, 'value': 0.0, 'cogs': 0.0,
                        'category': q.product_id.categ_id.name or '', 'lines': [],
                    }
                pivot_data[key]['qty'] += q.quantity
                pivot_data[key]['value'] += q.quantity * (q.product_id.standard_price or 0.0)
            for m in out_moves:
                key = m.product_id.display_name or 'Unknown'
                if key not in pivot_data:
                    pivot_data[key] = {'qty': 0.0, 'value': 0.0, 'cogs': 0.0, 'category': '', 'lines': []}
                cost = m.product_uom_qty * (m.price_unit or m.product_id.standard_price or 0.0)
                pivot_data[key]['cogs'] += cost
                if detailed_excel:
                    pivot_data[key]['lines'].append({
                        'name': m.reference or (m.picking_id.name if m.picking_id else ''),
                        'qty': m.product_uom_qty, 'cost': cost, 'date': str(m.date.date()),
                    })

        elif export_group == 'category':
            for q in quants:
                key = q.product_id.categ_id.name or 'Uncategorized'
                if key not in pivot_data:
                    pivot_data[key] = {'qty': 0.0, 'value': 0.0, 'cogs': 0.0, 'lines': []}
                pivot_data[key]['qty'] += q.quantity
                pivot_data[key]['value'] += q.quantity * (q.product_id.standard_price or 0.0)
            for m in out_moves:
                key = m.product_id.categ_id.name or 'Uncategorized'
                if key not in pivot_data:
                    pivot_data[key] = {'qty': 0.0, 'value': 0.0, 'cogs': 0.0, 'lines': []}
                pivot_data[key]['cogs'] += m.product_uom_qty * (m.price_unit or m.product_id.standard_price or 0.0)

        elif export_group == 'location':
            for q in quants:
                key = q.location_id.complete_name or q.location_id.name or 'Unknown'
                if key not in pivot_data:
                    pivot_data[key] = {'qty': 0.0, 'value': 0.0, 'cogs': 0.0, 'lines': []}
                pivot_data[key]['qty'] += q.quantity
                pivot_data[key]['value'] += q.quantity * (q.product_id.standard_price or 0.0)

        elif export_group == 'warehouse':
            for q in quants:
                wh = self.env['stock.warehouse'].search(
                    [('view_location_id', 'parent_of', q.location_id.id)], limit=1
                )
                key = wh.name if wh else 'Unknown'
                if key not in pivot_data:
                    pivot_data[key] = {'qty': 0.0, 'value': 0.0, 'cogs': 0.0, 'lines': []}
                pivot_data[key]['qty'] += q.quantity
                pivot_data[key]['value'] += q.quantity * (q.product_id.standard_price or 0.0)

        for data in pivot_data.values():
            data['turnover'] = round(data['cogs'] / data['value'], 3) if data['value'] > 0 else 0.0

        output = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        sheet = workbook.add_worksheet('Inventory Analysis')
        if detailed_excel:
            sheet.outline_settings(symbols_below=False)

        header_fmt = workbook.add_format({'bold': True, 'bg_color': '#1e3a5f', 'font_color': 'white', 'border': 1, 'align': 'center'})
        money_fmt = workbook.add_format({'num_format': '#,##0.00', 'border': 1})
        num_fmt = workbook.add_format({'border': 1, 'align': 'center'})
        text_fmt = workbook.add_format({'border': 1, 'bold': True, 'bg_color': '#f0f4ff'})
        detail_txt_fmt = workbook.add_format({'border': 1, 'indent': 1, 'font_color': '#475569'})
        detail_money_fmt = workbook.add_format({'num_format': '#,##0.00', 'border': 1, 'font_color': '#475569', 'bg_color': '#ffffff'})

        group_titles = {'product': 'Product', 'category': 'Category', 'location': 'Location', 'warehouse': 'Warehouse'}
        headers = [group_titles.get(export_group, 'Group')]
        if 'qty' in export_measures: headers.append('Qty On Hand')
        if 'value' in export_measures: headers.append('Stock Value (EGP)')
        if 'cogs' in export_measures: headers.append('COGS (EGP)')
        if 'turnover' in export_measures: headers.append('Turnover Rate')
        if export_group == 'product' and 'category' in export_measures: headers.append('Category')

        for col, h in enumerate(headers):
            sheet.write(0, col, h, header_fmt)
            sheet.set_column(col, col, 40 if col == 0 else 22)

        row = 1
        for key, data in sorted(pivot_data.items(), key=lambda x: x[1]['value'], reverse=True):
            sheet.write(row, 0, str(key), text_fmt)
            col = 1
            if 'qty' in export_measures: sheet.write(row, col, data['qty'], num_fmt); col += 1
            if 'value' in export_measures: sheet.write(row, col, data['value'], money_fmt); col += 1
            if 'cogs' in export_measures: sheet.write(row, col, data['cogs'], money_fmt); col += 1
            if 'turnover' in export_measures: sheet.write(row, col, data.get('turnover', 0), num_fmt); col += 1
            if export_group == 'product' and 'category' in export_measures: sheet.write(row, col, data.get('category', ''), text_fmt); col += 1

            if detailed_excel and data.get('lines'):
                sheet.set_row(row, None, None, {'collapsed': True})
                row += 1
                for line in data['lines']:
                    sheet.write(row, 0, "   -> {} ({})".format(line['name'], line['date']), detail_txt_fmt)
                    col = 1
                    if 'qty' in export_measures: sheet.write(row, col, line['qty'], detail_money_fmt); col += 1
                    if 'value' in export_measures: sheet.write(row, col, 0, detail_money_fmt); col += 1
                    if 'cogs' in export_measures: sheet.write(row, col, line['cost'], detail_money_fmt); col += 1
                    if 'turnover' in export_measures: sheet.write(row, col, 0, detail_money_fmt); col += 1
                    sheet.set_row(row, None, None, {'level': 1, 'hidden': True})
                    row += 1
            else:
                row += 1

        workbook.close()
        output.seek(0)
        attachment = self.env['ir.attachment'].create({
            'name': 'Inventory_Export_{}.xlsx'.format(fields.Date.today()),
            'type': 'binary',
            'datas': base64.b64encode(output.read()).decode('utf-8'),
            'mimetype': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        })
        return attachment.id