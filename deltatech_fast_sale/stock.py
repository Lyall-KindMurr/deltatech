# -*- coding: utf-8 -*-


from odoo import api, models


class StockPicking(models.Model):
    _inherit = 'stock.picking'

    @api.multi
    def action_view_sale_invoice(self):
        if self.sale_id:
            action_obj = self.env.ref('sale.action_view_sale_advance_payment_inv')
            action = action_obj.read()[0]
            action['context'] = {'active_id': self.sale_id.id,
                                 'active_ids': self.sale_id.ids,
                                 'notice':True}
            return action
