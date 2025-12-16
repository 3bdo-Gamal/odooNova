from odoo import models, fields, api


class SalesDashboard(models.Model):
    _name = 'wb.sales.dashboard'
    _description = 'Sales KPI Dashboard'

    name = fields.Char(default="Sales Dashboard")
    currency_id = fields.Many2one('res.currency', default=lambda self: self.env.company.currency_id)


    total_sales = fields.Monetary(string="Total Revenue", compute="_compute_kpis")


    orders_count = fields.Integer(string="Orders Count", compute="_compute_kpis")


    average_order_value = fields.Monetary(string="AOV", compute="_compute_kpis")


    total_invoiced = fields.Monetary(string="Invoiced", compute="_compute_kpis")

    def _compute_kpis(self):
        for record in self:

            orders = self.env['sale.order'].search([('state', 'in', ['sale', 'done'])])


            record.orders_count = len(orders)
            record.total_sales = sum(order.amount_total for order in orders)


            if record.orders_count > 0:
                record.average_order_value = record.total_sales / record.orders_count
            else:
                record.average_order_value = 0.0


            invoices = self.env['account.move'].search([
                ('move_type', '=', 'out_invoice'),
                ('state', '=', 'posted')
            ])
            record.total_invoiced = sum(inv.amount_total for inv in invoices)
