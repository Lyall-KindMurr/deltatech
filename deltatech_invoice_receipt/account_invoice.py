# -*- coding: utf-8 -*-
##############################################################################
#
# Copyright (c) 2015 Deltatech All Rights Reserved
#                    Dorin Hongu <dhongu(@)gmail(.)com       
#
#    This program is free software: you can redistribute it and/or modify
#    it under the terms of the GNU Affero General Public License as
#    published by the Free Software Foundation, either version 3 of the
#    License, or (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU Affero General Public License for more details.
#
#    You should have received a copy of the GNU Affero General Public License
#    along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
##############################################################################

from openerp import models, fields, api, _
import openerp.addons.decimal_precision as dp
from openerp.exceptions import except_orm, Warning, RedirectWarning
from openerp.tools import DEFAULT_SERVER_DATETIME_FORMAT, DEFAULT_SERVER_DATE_FORMAT,DEFAULT_SERVER_TIME_FORMAT
import time 
from datetime import datetime

class account_invoice(models.Model):
    _inherit = "account.invoice"
    
    """
    # camp pt a indica din ce factura se face stornarea
    origin_refund_invoice_id = fields.Many2one('account.invoice', string='Origin Invoice',   copy=False)
    # camp prin care se indica prin ce factura se face stornarea 
    refund_invoice_id = fields.Many2one('account.invoice', string='Refund Invoice',    copy=False)
    """
    @api.model
    def get_link(self, model ):
        for model_id, model_name in model.name_get():
            link = "<a href='#id=%s&model=%s'>%s</a>" % (str(model_id), model._name, model_name )
        return link
    
    """     
    @api.multi
    @api.returns('self')
    def refund(self, date=None, period_id=None, description=None, journal_id=None):
        new_invoices = super(account_invoice, self).refund(date, period_id, description,journal_id )
        new_invoices.write({'origin_refund_invoice_id':self.id})
        self.write({'refund_invoice_id':new_invoices.id})
        msg = _('Invoice %s was refunded by %s') % (self.get_link(self),  self.get_link(new_invoices))
        self.message_post(body=msg)
        new_invoices.message_post(body=msg)
        return new_invoices        
    """
    
    
    @api.one
    def check_invoice_with_delivery(self):
        if self.type != 'in_invoice':
            for line in self.invoice_line:
                if line.product_id.type == 'product': 
                    ok = False
                    for picking in self.picking_ids:
                        for move in picking.move_lines:
                            if move.product_id == line.product_id:
                                ok = True
                                break
                        if ok:
                            break
                    if not ok:
                       raise except_orm(_('Delivery not found!'),
                                        _('No delivery line for product %s') % line.product_id.name)
        return 
    
    @api.multi
    def invoice_create_picking(self):  
        if self.picking_ids or self.type != 'in_invoice':
            return
        
        date_eval = self.date_invoice or fields.Date.context_today(self) 
        date_receipt = date_eval + ' ' + time.strftime(DEFAULT_SERVER_TIME_FORMAT)
        from_currency = self.currency_id.with_context(date=date_eval)
        
        picking_value = {
                          'partner_id':self.partner_id.id,
                          'date':date_receipt,
                          'picking_type_id':self.env.ref('stock.picking_type_in').id,
                          'invoice_id':self.id,    
                          'origin':self.supplier_invoice_number,     
                         }
        picking = self.env['stock.picking'].create(picking_value)
        for line in self.invoice_line:
            if line.product_id.type == 'product':
                price = line.price_unit * (1 - (line.discount or 0.0) / 100.0)
                price = from_currency.compute(price, self.env.user.company_id.currency_id )
                move_value= {
                               'product_id':line.product_id.id,
                               'product_uom_qty':line.quantity,
                               'product_uom':line.product_id.uom_id.id,
                               'name':line.name,
                               'location_id':self.env.ref('stock.stock_location_suppliers').id,
                               'location_dest_id':self.env.ref('stock.stock_location_stock').id,
                               'invoice_state':'invoiced',
                               'invoice_line_id':line.id, 
                               'picking_id':picking.id,
                               'price_unit': price,
                               'date_expected': date_receipt 
                            }
                self.env['stock.move'].create(move_value)
        picking.action_confirm()
        picking.do_transfer()        
        msg = _('Picking list %s without reference to purchase order was created') % self.get_link(picking)
        self.message_post(body=msg)
        picking.message_post(body=msg)
        
        
                
    @api.multi
    def invoice_create_receipt(self):   
        for picking in  self.picking_ids:
            if picking.state in ['assigned']:
                picking.do_transfer()
        if self.origin_refund_invoice_id:
            # e o factura de rambursare asa ca nu mai am ce face
            return             

        self.check_invoice_with_delivery() 

        #trebuie sa verific ca factura nu este generata dintr-un flux normal de achiztie !!
        if self.type not in ['in_invoice' ,'in_refund']: 
            return
        
        
        date_eval = self.date_invoice or fields.Date.context_today(self) 
        date_receipt = date_eval + ' ' + time.strftime(DEFAULT_SERVER_TIME_FORMAT)
        from_currency = self.currency_id.with_context(date=date_eval)
         
        # trebuie definita o matrice in care sa salvez liniile din factura impreuna cu cantitatile aferente.
        lines = []
        for line in self.invoice_line:
            if line.product_id.type == 'product': 
                ok = True
                moves = self.env['stock.move'].search([('invoice_line_id','=',line.id)] ) 
                for move in moves:
                    if move.state == 'done':                       # dar daca am receptii partiale pe aceasta linie ???
                        ok = False
                
                """
                purchase_line_ids = self.env['purchase.order.line'].search([('invoice_lines','=', line.id)])
                ok = True
                if purchase_line_ids:
                    for purchase_line in purchase_line_ids:
                        # oare sunt facute receptii de aceste  comenzi (factura generata din comanda sau din linii de comanda)
                        for move in purchase_line.move_ids:
                            if move.state == 'done':                       # dar daca am receptii partiale pe aceasta linie ???
                                ok = False
                """
                if ok:             
                    price = line.price_unit * (1 - (line.discount or 0.0) / 100.0)
                    lines.append({'invoice_line': line,
                                  'product_id':line.product_id,
                                  'quantity':  line.quantity,
                                  'price_unit':  from_currency.compute(price, self.env.user.company_id.currency_id )
                                   })                  # pretul trebuie convertit in moneda codului de companie!!     
        
        if not lines:
            return
 
        # se va completa la produsele stocabile contul 408
        stock_picking_payable_account_id = self.company_id and self.company_id.property_stock_picking_payable_account_id and self.company_id.property_stock_picking_payable_account_id.id 
        if stock_picking_payable_account_id:
            for line in lines:
                line['invoice_line'].write({'account_id':stock_picking_payable_account_id})
 
         # caut  picking listurile pregatite pt receptie de la acest furnizor
   
        domain=[('state', '=', 'assigned'),('partner_id','=',self.partner_id.id)]
        pickings = self.env['stock.picking'].search(domain, order='date ASC',) 
        if not pickings:
            raise except_orm(_('Picking not found!'),
                             _('No purchase orders from this supplier'))
        
        # caut liniile care au cantitate zero si nu sunt anulate si le anulez
        for picking in pickings:
            for move in picking.move_lines:
                if move.product_uom_qty == 0 and move.state == 'assigned':
                    move.write({'state':'cancel'})
 
        # pregatire picking list pentru receptii partiale
        for picking in pickings:
            if not picking.pack_operation_exist:
                picking.do_prepare_partial()
            
        # memorez intr-o lista operatiile pregatite de receptie
        operations = self.env['stock.pack.operation']
        
        for picking in pickings:
            if picking.picking_type_id.code == 'incoming':
                operations = operations |  picking.pack_operation_ids

    
        operations = operations.sorted(key=lambda r: r.date)
       
        quantities = {} 
        for op  in operations:
            quantities[op.id] = op.product_qty
            
        new_picking_line = []
        
        is_ok = True
        while is_ok:                     
            is_ok = False
            for line in lines:
                if line['quantity'] > 0 :
                    for op in operations:
                        if quantities[op.id] > 0 and line['quantity'] > 0 and op.product_id.id == line['product_id'].id:
                            # am gasit o line de comanda din care se poate scade o cantitate  
                            is_ok = True                                                                   
                            if quantities[op.id] >= line['quantity']:
                                new_picking_line.append({'picking':op.picking_id,
                                                         'operation':op,
                                                         'product_id':op.product_id, 
                                                         'product_qty':line['quantity'],
                                                         'price_unit':line['price_unit'],
                                                         'invoice_line': line['invoice_line']})                 
                                qty = line['quantity']
                                qty = quantities[op.id]  #scad toata cantitatea pentru ca nu stiu cum sa gestionez accelasi produs de mai multe ori pe factura
                                line['quantity'] = 0 
                            else:
                                new_picking_line.append({'picking':op.picking_id,
                                                         'operation':op,
                                                         'product_id':op.product_id, 
                                                         'product_qty':quantities[op.id],
                                                         'price_unit':line['price_unit'],
                                                         'invoice_line': line['invoice_line']})

                                qty = quantities[op.id]
                                line['quantity'] =  line['quantity'] - quantities[op.id]
                            quantities[op.id] = quantities[op.id] - qty   
                            
        
        for line in lines:
           if line['quantity'] > 0:
               raise except_orm(_('Picking not found!'),
                                _('No purchase orders line from product %s in quantity of %s ') % (line['product_id'].name, line['quantity'] )  )
            
        # sa incepem receptia
        processed_ids = []
        purchase_line_ids = []
        
        purchase_ids = self.env['purchase.order']
        
        for line in new_picking_line:
            op = line['operation']
            op.write({'product_qty': line['product_qty'], 
                      'date':date_receipt}) ## asta insemana ca nu trebuie sa scad de doua ori dint-o operatie
            processed_ids.append(op.id)    
            for link in op.linked_move_operation_ids:
                purchase_line_ids.append(link.move_id.purchase_line_id)
                link.move_id.write({
                                    'price_unit': line['price_unit'],
                                    'date_expected': date_receipt ,
                                    'invoice_line_id':line['invoice_line'].id,
                                    })
                
                if line['product_id'].cost_method == 'real' and  line['product_id'].standard_price <> line['price_unit']:
                    line['product_id'].write({'standard_price':line['price_unit']})   # actualizare pret cu ultimul pret din factura!!
                    
                link.move_id.purchase_line_id.write({'invoice_lines': [(4, line['invoice_line'].id)]})
                purchase_ids = purchase_ids | link.move_id.purchase_line_id.order_id
                #link.move_id.purchase_line_id.order_id.write({'invoice_ids': [(4, line['invoice_line'].invoice_id.id)]}) 
                
        if purchase_ids:
            purchase_ids.write({'invoice_ids': [(4, self.id)]})
            msg_for_PO = _('Was entered invoice %s') % self.get_link(self)    
            
            msg = _('Was enter reception for purchase order:')
            for purchase in purchase_ids:
                purchase.message_post(body=msg_for_PO)
                msg =  msg + ' '+ self.get_link(purchase)
            self.message_post(body=msg)
 
        for line in new_picking_line:
            if line['picking'].state == 'assigned':
                # Delete the others
                packops = self.env['stock.pack.operation'].search(['&', ('picking_id', '=', line['picking'].id), '!', ('id', 'in', processed_ids)])
                for packop in packops:
                    packop.unlink()                
        origin = ''
        for line in new_picking_line:
            if line['picking'].state == 'assigned': 
                if stock_picking_payable_account_id:
                    line['picking'].write({'notice': True})                 
                line['picking'].do_transfer()
                line['picking'].write({'date_done': date_receipt,  
                                       'invoice_state':'invoiced',
                                       'invoice_id':self.id,
                                       #'reception_to_invoice':False, 
                                       'origin':self.supplier_invoice_number or line['picking'].origin })
                msg = _('Picking list %s was receipted') % self.get_link(line['picking'])
                origin = origin + ' '+ line['picking'].name
                self.message_post(body=msg)
       

            
        if not self.origin:
            self.write({'origin':origin.strip()})

    @api.model
    def create(self, vals):
        journal_id = vals.get('journal_id',self.default_get(['journal_id'])['journal_id'])
        currency_id = vals.get('currency_id',self.default_get(['currency_id'])['currency_id'])
        
        
        if journal_id  and currency_id:
            journal = self.env['account.journal'].browse(journal_id)
            to_currency = journal.currency or self.env.user.company_id.currency_id
            if  to_currency.id != currency_id:
                date_invoice = vals.get('date_invoice', fields.Date.context_today(self))  
                vals['date_invoice'] = date_invoice
                from_currency = self.env['res.currency'].with_context(date=date_invoice).browse(currency_id)
                invoice_line = vals.get('invoice_line',False)
                if invoice_line:
                    for a,b,line in invoice_line:
                        line_obj = self.env['account.invoice.line'].browse(line)
                        if line_obj:
                            line_obj.price_unit  = from_currency.compute( line_obj.price_unit,to_currency)
                        
                    vals['currency_id'] = to_currency.id
        inv_id = super(account_invoice,self).create(vals)
         
        return inv_id
              
class account_invoice_line(models.Model):
    _inherit = "account.invoice.line"


    @api.multi
    def unlink(self):
        # de verificat daca sunt miscari din liste de ridicare care au statusul Facturat!
        res = super(account_invoice_line, self).unlink()
        return res

        
    @api.multi
    # pretul din factura se determina in functie de cursul de schimb din data facturii  
    def product_id_change(self, product, uom_id, qty=0, name='', type='out_invoice',
            partner_id=False, fposition_id=False, price_unit=False, currency_id=False,
            company_id=None):
 
        res = super(account_invoice_line, self).product_id_change(  product, uom_id, qty, name, type,
            partner_id, fposition_id, price_unit, currency_id, company_id)
        
        if product:
            product_obj = self.env['product.product'].browse(product)
            currency = self.env['res.currency'].browse(currency_id)
            part = self.env['res.partner'].browse(partner_id)
            
            if type == 'out_invoice' and  part.property_product_pricelist:
                pricelist_id = part.property_product_pricelist.id
                price_unit = part.property_product_pricelist.price_get(product,qty, partner_id)[pricelist_id]
                from_currency = part.property_product_pricelist.currency_id or self.env.user.company_id.currency_id
                if currency and  from_currency:
                    res['value']['price_unit'] = from_currency.compute(price_unit, currency)
    
            if type == 'in_invoice' and part.property_product_pricelist_purchase:
                pricelist_id = part.property_product_pricelist_purchase.id
                price_unit = part.property_product_pricelist_purchase.price_get(product,qty, partner_id )[pricelist_id]
                from_currency = part.property_product_pricelist_purchase.currency_id or self.env.user.company_id.currency_id
                if currency and  from_currency:
                    res['value']['price_unit'] = from_currency.compute(price_unit, currency)

            # oare e bine sa las asa ?????
            # cred ca mai trebuie pus un camp in produs prin care sa se specifice clar care din produse intra prin 408
            if type == 'in_invoice':
                if  product_obj.type == 'product':
                    account_id = self.env.user.company_id and self.env.user.company_id.property_stock_picking_payable_account_id and   self.env.user.company_id.property_stock_picking_payable_account_id.id
                    if  not account_id: 
                        account_id = product_obj.property_stock_account_input and product_obj.property_stock_account_input.id or False
                        if not account_id:
                            account_id = product_obj.categ_id.property_stock_account_input_categ and product_obj.categ_id.property_stock_account_input_categ.id or False

                    res['value']['account_id'] = account_id
                  
        
        return res     

# vim:expandtab:smartindent:tabstop=4:softtabstop=4:shiftwidth=4:



 
