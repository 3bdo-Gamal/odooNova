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

    # ─────────────────────────────────────────────────────────────────────────
    # Helper: build all filtered domains from the shared filter parameters
    # ─────────────────────────────────────────────────────────────────────────
    def _build_domains(self, period, date_from, date_to,
                       warehouse_id, product_id, category_id, location_id):
        """
        Returns (dt_from, dt_to, days_count, product_domain,
                 quant_domain, move_out_domain, move_in_domain)
        """
        today = datetime.now()

        if date_from and date_to:
            dt_from = datetime.strptime(date_from, '%Y-%m-%d')
            dt_to = datetime.strptime(date_to, '%Y-%m-%d').replace(
                hour=23, minute=59, second=59
            )
        else:
            try:
                period = int(period)
            except Exception:
                period = 30
            dt_to = today
            dt_from = today - timedelta(days=period)

        days_count = max((dt_to - dt_from).days + 1, 1)

        # ── base domains ───────────────────────────────────────────────────
        product_domain = [('detailed_type', '=', 'product')]

        # Quants: physical stock sitting in internal locations right now
        quant_domain = [('location_id.usage', '=', 'internal')]

        # FIX #1 ─ Out moves: deliveries FROM internal stock TO customers only
        #   Old code had no constraint on location_id.usage, so it also captured
        #   production outputs, inter-warehouse transfers, etc.
        move_out_domain = [
            ('state', '=', 'done'),
            ('location_id.usage', '=', 'internal'),       # shipped FROM warehouse
            ('location_dest_id.usage', '=', 'customer'),  # delivered TO customer
            ('date', '>=', dt_from),
            ('date', '<=', dt_to),
        ]

        # FIX #2 ─ In moves: receipts FROM suppliers TO internal stock only
        #   Old code used ('location_dest_id.usage', '=', 'internal') with NO
        #   constraint on origin location, so it counted internal transfers,
        #   manufacturing outputs, customer returns, etc. as "received from supplier".
        move_in_domain = [
            ('state', '=', 'done'),
            ('location_id.usage', '=', 'supplier'),       # shipped FROM supplier
            ('location_dest_id.usage', '=', 'internal'),  # received INTO warehouse
            ('date', '>=', dt_from),
            ('date', '<=', dt_to),
        ]

        # ── optional filters ──────────────────────────────────────────────
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

    # ─────────────────────────────────────────────────────────────────────────
    # Main KPI method
    # ─────────────────────────────────────────────────────────────────────────
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
        (dt_from, dt_to, days_count,
         product_domain, quant_domain,
         move_out_domain, move_in_domain) = self._build_domains(
            period, date_from, date_to,
            warehouse_id, product_id, category_id, location_id
        )

        products  = self.env['product.product'].search(product_domain)
        quants    = self.env['stock.quant'].search(quant_domain)
        out_moves = self.env['stock.move'].search(move_out_domain)
        in_moves  = self.env['stock.move'].search(move_in_domain)

        # ══════════════════════════════════════════════════════════════════
        # KPI 1 ─ Stock On Hand (units)
        # Simple sum of available quantity across all matching quants.
        # ══════════════════════════════════════════════════════════════════
        stock_on_hand = sum(quants.mapped('quantity'))

        # ══════════════════════════════════════════════════════════════════
        # KPI 2 ─ Ending Stock Value
        # Ending Stock Value = Σ (qty_on_hand × standard_cost)
        # We use standard_price because it is the configured cost price for
        # the product and is consistent regardless of costing method used for
        # journal entries (Standard / AVCO / FIFO).
        # ══════════════════════════════════════════════════════════════════
        ending_stock_value = sum(
            q.quantity * (q.product_id.standard_price or 0.0) for q in quants
        )

        # ══════════════════════════════════════════════════════════════════
        # KPI 3 ─ COGS for the selected period
        # COGS = Σ (qty_done × standard_cost) for all outgoing (delivery) moves
        #
        # FIX #3 ─ old code used  m.price_unit  which is the sales price
        # stored on the stock move for some flows, not the COST price.
        # standard_price is the correct cost to use here.
        # For AVCO/FIFO companies that need valuation-layer accuracy they
        # can replace this with stock.valuation.layer queries.
        # ══════════════════════════════════════════════════════════════════
        cogs = sum(
            m.product_uom_qty * (m.product_id.standard_price or 0.0)
            for m in out_moves
        )

        # ══════════════════════════════════════════════════════════════════
        # KPI 4 ─ Value Received from Suppliers (period)
        # Received Value = Σ (qty_received × standard_cost)
        # Same reasoning as COGS: use standard_price, not price_unit.
        # ══════════════════════════════════════════════════════════════════
        received_value = sum(
            m.product_uom_qty * (m.product_id.standard_price or 0.0)
            for m in in_moves
        )

        # ══════════════════════════════════════════════════════════════════
        # KPI 5 ─ Inventory Turnover Ratio  (annualized)
        #
        # Formula:  Turnover = (COGS_period / Ending_Stock_Value)
        #                      × (365 / days_count)
        #
        # FIX #4 ─ old code: cogs / ending_stock_value — no annualization.
        # Without annualization a 7-day period with the same daily sales rate
        # gives a turnover 52× lower than a yearly view, making the KPI
        # meaningless for short periods. Annualizing lets you compare to
        # industry benchmarks regardless of the chosen date range.
        #
        # NOTE: "Average Inventory" = (Begin + End) / 2 is the textbook form,
        # but beginning inventory requires an extra historical query.
        # Using ending inventory is the standard dashboard approximation.
        # ══════════════════════════════════════════════════════════════════
        if ending_stock_value > 0 and cogs > 0:
            raw_turnover = cogs / ending_stock_value          # ratio for period
            inventory_turnover = round(raw_turnover * (365.0 / days_count), 2)
        else:
            raw_turnover = 0.0
            inventory_turnover = 0.0

        # ══════════════════════════════════════════════════════════════════
        # KPI 6 ─ DIO  (Days Inventory Outstanding / Days in Stock)
        #
        # Formula:  DIO = (Ending_Stock_Value / COGS_period) × days_count
        #
        # Business meaning: "At the current period's sales rate, how many
        # days will existing stock last?"
        #
        # FIX #5 ─ old code used  365 / inventory_turnover  which always
        # produced a year-based figure even when the user chose 7 days,
        # and capped the result arbitrarily at 365 days.
        # ══════════════════════════════════════════════════════════════════
        if cogs > 0:
            dio = round((ending_stock_value / cogs) * days_count, 1)
        else:
            # No sales at all in the period → inventory is not moving
            # DIO is undefined; we show it as the full period length as a
            # conservative "still in stock" indicator.
            dio = days_count

        # ══════════════════════════════════════════════════════════════════
        # KPI 7 ─ Low Stock Count
        #
        # FIX #6 ─ old code: qty_available <= 0  → that is OUT-OF-STOCK,
        # not low stock.  Low stock means qty is at or below the configured
        # reorder minimum (stock.warehouse.orderpoint.product_min_qty).
        # Products with no reorder rule fall back to qty_available <= 0.
        # ══════════════════════════════════════════════════════════════════
        orderpoints = self.env['stock.warehouse.orderpoint'].search([])
        # Map: product_id → minimum qty before reorder triggers
        reorder_min_map = {}
        for op in orderpoints:
            pid = op.product_id.id
            # If multiple orderpoints for same product, take the highest min_qty
            reorder_min_map[pid] = max(
                reorder_min_map.get(pid, 0.0),
                op.product_min_qty
            )

        low_stock_count = 0
        for product in products:
            on_hand = product.qty_available
            min_qty = reorder_min_map.get(product.id, 0.0)
            # "Low stock" = on hand has reached (or gone below) the reorder point
            if on_hand <= min_qty:
                low_stock_count += 1

        # ══════════════════════════════════════════════════════════════════
        # KPI 8 ─ Dead Stock
        # Products that have stock on hand but had ZERO movement (in or out)
        # during the entire selected period.
        # ══════════════════════════════════════════════════════════════════
        moved_product_ids = (
            set(out_moves.mapped('product_id').ids)
            | set(in_moves.mapped('product_id').ids)
        )
        dead_stock_products = products.filtered(
            lambda p: p.id not in moved_product_ids and p.qty_available > 0
        )

        # ══════════════════════════════════════════════════════════════════
        # Chart: Stock Movement Trend  (daily in / out quantities)
        # ══════════════════════════════════════════════════════════════════
        daily_in  = {}
        daily_out = {}
        for i in range(days_count):
            key = (dt_from + timedelta(days=i)).strftime('%Y-%m-%d')
            daily_in[key]  = 0.0
            daily_out[key] = 0.0

        for m in in_moves:
            key = m.date.strftime('%Y-%m-%d')
            if key in daily_in:
                daily_in[key] += m.product_uom_qty

        for m in out_moves:
            key = m.date.strftime('%Y-%m-%d')
            if key in daily_out:
                daily_out[key] += m.product_uom_qty

        # ══════════════════════════════════════════════════════════════════
        # Chart: ABC Analysis – Stock Value by Category
        # ══════════════════════════════════════════════════════════════════
        abc_labels = []
        abc_data   = []
        for cat in self.env['product.category'].search([]):
            cat_quants = quants.filtered(lambda q: q.product_id.categ_id == cat)
            val = sum(
                q.quantity * (q.product_id.standard_price or 0.0)
                for q in cat_quants
            )
            if val > 0:
                abc_labels.append(cat.name)
                abc_data.append(round(val, 2))

        # ══════════════════════════════════════════════════════════════════
        # Chart: Top Products by Quantity Out (delivered to customers)
        # ══════════════════════════════════════════════════════════════════
        product_out = {}
        for m in out_moves:
            name = m.product_id.display_name or 'Unknown'
            product_out[name] = product_out.get(name, 0.0) + m.product_uom_qty
        sorted_products = sorted(product_out.items(), key=lambda x: x[1], reverse=True)[:10]

        # ══════════════════════════════════════════════════════════════════
        # Chart: Stock Distribution by Location
        # ══════════════════════════════════════════════════════════════════
        location_stock = {}
        for q in quants:
            loc_name = q.location_id.complete_name or q.location_id.name or 'Unknown'
            location_stock[loc_name] = location_stock.get(loc_name, 0.0) + q.quantity
        sorted_locations = sorted(
            location_stock.items(), key=lambda x: x[1], reverse=True
        )[:10]

        return {
            'stock_on_hand':       round(stock_on_hand, 2),
            'stock_value':         round(ending_stock_value, 2),
            'stock_value_fmt':     "{:,.2f}".format(ending_stock_value),
            'cogs':                round(cogs, 2),
            'cogs_fmt':            "{:,.2f}".format(cogs),
            'received_value':      round(received_value, 2),
            # Annualized ratio, e.g. "4.5x"
            'inventory_turnover':  "{}x".format(inventory_turnover),
            # Days current stock will last at current sales rate
            'dio':                 "{} Days".format(int(dio)),
            'low_stock_count':     low_stock_count,
            'dead_stock_count':    len(dead_stock_products),
            'total_products':      len(products),
            'trend_labels':        list(daily_in.keys()),
            'trend_in':            list(daily_in.values()),
            'trend_out':           list(daily_out.values()),
            'abc_labels':          abc_labels,
            'abc_data':            abc_data,
            'top_product_labels':  [i[0] for i in sorted_products],
            'top_product_data':    [i[1] for i in sorted_products],
            'location_labels':     [i[0] for i in sorted_locations],
            'location_data':       [i[1] for i in sorted_locations],
        }

    # ─────────────────────────────────────────────────────────────────────────
    # Excel Export  (same fixes applied)
    # ─────────────────────────────────────────────────────────────────────────
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

        (dt_from, dt_to, days_count,
         product_domain, quant_domain,
         move_out_domain, move_in_domain) = self._build_domains(
            period, date_from, date_to,
            warehouse_id, product_id, category_id, 'all'
        )

        quants    = self.env['stock.quant'].search(quant_domain)
        out_moves = self.env['stock.move'].search(move_out_domain)
        in_moves  = self.env['stock.move'].search(move_in_domain)

        pivot_data = {}

        # ── group data ────────────────────────────────────────────────────
        if export_group == 'product':
            for q in quants:
                key = q.product_id.display_name or 'Unknown'
                if key not in pivot_data:
                    pivot_data[key] = {
                        'qty': 0.0, 'value': 0.0, 'cogs': 0.0,
                        'category': q.product_id.categ_id.name or '',
                        'lines': [],
                    }
                pivot_data[key]['qty']   += q.quantity
                # FIX: standard_price not price_unit
                pivot_data[key]['value'] += q.quantity * (q.product_id.standard_price or 0.0)

            for m in out_moves:
                key = m.product_id.display_name or 'Unknown'
                if key not in pivot_data:
                    pivot_data[key] = {
                        'qty': 0.0, 'value': 0.0, 'cogs': 0.0,
                        'category': m.product_id.categ_id.name or '',
                        'lines': [],
                    }
                # FIX: standard_price not price_unit
                cost = m.product_uom_qty * (m.product_id.standard_price or 0.0)
                pivot_data[key]['cogs'] += cost
                if detailed_excel:
                    pivot_data[key]['lines'].append({
                        'name': m.reference or (m.picking_id.name if m.picking_id else ''),
                        'qty': m.product_uom_qty,
                        'cost': cost,
                        'date': str(m.date.date()),
                    })

        elif export_group == 'category':
            for q in quants:
                key = q.product_id.categ_id.name or 'Uncategorized'
                if key not in pivot_data:
                    pivot_data[key] = {'qty': 0.0, 'value': 0.0, 'cogs': 0.0, 'lines': []}
                pivot_data[key]['qty']   += q.quantity
                pivot_data[key]['value'] += q.quantity * (q.product_id.standard_price or 0.0)
            for m in out_moves:
                key = m.product_id.categ_id.name or 'Uncategorized'
                if key not in pivot_data:
                    pivot_data[key] = {'qty': 0.0, 'value': 0.0, 'cogs': 0.0, 'lines': []}
                pivot_data[key]['cogs'] += m.product_uom_qty * (m.product_id.standard_price or 0.0)

        elif export_group == 'location':
            for q in quants:
                key = q.location_id.complete_name or q.location_id.name or 'Unknown'
                if key not in pivot_data:
                    pivot_data[key] = {'qty': 0.0, 'value': 0.0, 'cogs': 0.0, 'lines': []}
                pivot_data[key]['qty']   += q.quantity
                pivot_data[key]['value'] += q.quantity * (q.product_id.standard_price or 0.0)

        elif export_group == 'warehouse':
            for q in quants:
                wh = self.env['stock.warehouse'].search(
                    [('view_location_id', 'parent_of', q.location_id.id)], limit=1
                )
                key = wh.name if wh else 'Unknown'
                if key not in pivot_data:
                    pivot_data[key] = {'qty': 0.0, 'value': 0.0, 'cogs': 0.0, 'lines': []}
                pivot_data[key]['qty']   += q.quantity
                pivot_data[key]['value'] += q.quantity * (q.product_id.standard_price or 0.0)

        # ── Turnover Rate per group (FIX: same corrected formula) ─────────
        for data in pivot_data.values():
            if data['value'] > 0 and data['cogs'] > 0:
                raw = data['cogs'] / data['value']
                data['turnover'] = round(raw * (365.0 / days_count), 2)
            else:
                data['turnover'] = 0.0

        # ── Build Excel ───────────────────────────────────────────────────
        output   = io.BytesIO()
        workbook = xlsxwriter.Workbook(output, {'in_memory': True})
        sheet    = workbook.add_worksheet('Inventory Analysis')
        if detailed_excel:
            sheet.outline_settings(symbols_below=False)

        header_fmt     = workbook.add_format({'bold': True, 'bg_color': '#1e3a5f', 'font_color': 'white', 'border': 1, 'align': 'center'})
        money_fmt      = workbook.add_format({'num_format': '#,##0.00', 'border': 1})
        num_fmt        = workbook.add_format({'border': 1, 'align': 'center'})
        text_fmt       = workbook.add_format({'border': 1, 'bold': True, 'bg_color': '#f0f4ff'})
        detail_txt_fmt = workbook.add_format({'border': 1, 'indent': 1, 'font_color': '#475569'})
        detail_money_fmt = workbook.add_format({'num_format': '#,##0.00', 'border': 1, 'font_color': '#475569', 'bg_color': '#ffffff'})

        group_titles = {
            'product': 'Product', 'category': 'Category',
            'location': 'Location', 'warehouse': 'Warehouse',
        }
        headers = [group_titles.get(export_group, 'Group')]
        if 'qty'      in export_measures: headers.append('Qty On Hand')
        if 'value'    in export_measures: headers.append('Stock Value (EGP)')
        if 'cogs'     in export_measures: headers.append('COGS — Period (EGP)')
        if 'turnover' in export_measures: headers.append('Turnover Rate (annualized)')
        if export_group == 'product' and 'category' in export_measures:
            headers.append('Category')

        for col, h in enumerate(headers):
            sheet.write(0, col, h, header_fmt)
            sheet.set_column(col, col, 40 if col == 0 else 25)

        row = 1
        for key, data in sorted(pivot_data.items(), key=lambda x: x[1]['value'], reverse=True):
            sheet.write(row, 0, str(key), text_fmt)
            col = 1
            if 'qty'      in export_measures: sheet.write(row, col, data['qty'],      num_fmt);   col += 1
            if 'value'    in export_measures: sheet.write(row, col, data['value'],    money_fmt); col += 1
            if 'cogs'     in export_measures: sheet.write(row, col, data['cogs'],     money_fmt); col += 1
            if 'turnover' in export_measures: sheet.write(row, col, data['turnover'], num_fmt);   col += 1
            if export_group == 'product' and 'category' in export_measures:
                sheet.write(row, col, data.get('category', ''), text_fmt); col += 1

            if detailed_excel and data.get('lines'):
                sheet.set_row(row, None, None, {'collapsed': True})
                row += 1
                for line in data['lines']:
                    sheet.write(row, 0,
                                "   -> {} ({})".format(line['name'], line['date']),
                                detail_txt_fmt)
                    col = 1
                    if 'qty'   in export_measures: sheet.write(row, col, line['qty'],  detail_money_fmt); col += 1
                    if 'value' in export_measures: sheet.write(row, col, 0,            detail_money_fmt); col += 1
                    if 'cogs'  in export_measures: sheet.write(row, col, line['cost'], detail_money_fmt); col += 1
                    if 'turnover' in export_measures: sheet.write(row, col, 0,         detail_money_fmt); col += 1
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