from odoo import  fields, models
class App_one(models.Model):
    _name = 'wb.app_one'
    _description = 'This is a custom model'

    name = fields.Char("Name")

