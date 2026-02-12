from odoo import models, fields

class ProductTemplate(models.Model):
    _inherit = 'product.template'

    ROP = fields.Integer(string="low-stock inventory level ", default=0)