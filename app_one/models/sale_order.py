
from odoo.exceptions import UserError, ValidationError
from odoo import api, fields, models, SUPERUSER_ID, _

class SaleOrderUpdate(models.Model):
    _inherit = 'sale.order'

    def action_confirm(self):
        for record in self:
            record.origin = "Ebram Kamal William"
            for line in record.order_line:
                line.product_uom_qty = 12
        return super().action_confirm()