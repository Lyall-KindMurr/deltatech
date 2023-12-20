# ©  2023 Deltatech
#              Dorin Hongu <dhongu(@)gmail(.)com
# See README.rst file on addons root folder for license details


import logging

from odoo import fields, models

_logger = logging.getLogger(__name__)


# ca in SAP Material Valuation - MBEW & MBEWH
class ProductValuation(models.Model):
    _name = "product.valuation"
    _description = "Product Valuation"
    _rec_name = "product_id"

    product_id = fields.Many2one("product.product", string="Product", required=True, index=True)
    valuation_area_id = fields.Many2one("valuation.area", string="Valuation Area", index=True)

    quantity = fields.Float(string="Quantity", digits="Product Unit of Measure")
    quantity_in = fields.Float(string="Quantity In", digits="Product Unit of Measure")
    quantity_out = fields.Float(string="Quantity Out", digits="Product Unit of Measure")

    amount = fields.Monetary(string="Amount")
    debit = fields.Monetary(string="Debit")
    credit = fields.Monetary(string="Credit")

    account_id = fields.Many2one("account.account", string="Account", required=True, index=True)

    currency_id = fields.Many2one("res.currency", string="Currency", default=lambda self: self.env.company.currency_id)
    company_id = fields.Many2one(
        "res.company", string="Company", required=True, index=True, default=lambda self: self.env.company
    )

    _sql_constraints = [
        (
            "product_valuation_uniq",
            "unique (product_id, valuation_area_id, account_id, company_id)",
            "Product valuation must be unique",
        )
    ]

    def get_valuation(self, product_id, valuation_area_id, account_id, company_id=False):
        if not company_id:
            company_id = self.env.company.id
        domain = [
            ("product_id", "=", product_id),
            ("valuation_area_id", "=", valuation_area_id),
            ("account_id", "=", account_id),
            ("company_id", "=", company_id),
        ]
        valuation = self.search(domain, limit=1)
        if not valuation:
            valuation = self.create(
                {
                    "product_id": product_id,
                    "valuation_area_id": valuation_area_id,
                    "account_id": account_id,
                    "company_id": company_id,
                }
            )
        return valuation

    def recompute_amount(self):
        valuation_areas = self.mapped("valuation_area_id")
        products = self.mapped("product_id")
        accounts = self.mapped("account_id")
        companies = self.mapped("company_id")
        domain = [
            ("product_id", "in", products.ids),
            ("account_id", "in", accounts.ids),
            ("company_id", "in", companies.ids),
        ]
        if valuation_areas:
            domain.append(("valuation_area_id", "in", valuation_areas.ids))

        params = {
            "product_ids": tuple(products.ids),
            "account_ids": tuple(accounts.ids),
            "company_ids": tuple(companies.ids),
            "valuation_area_ids": tuple(valuation_areas.ids) or (None,),
        }
        self.env.cr.execute(
            """
            SELECT product_id, valuation_area_id, account_id, m.company_id,
                sum(l.debit) as debit, sum(l.credit) as credit, sum(
                    l.quantity / NULLIF(COALESCE(uom_line.factor, 1) / COALESCE(uom_template.factor, 1), 0.0) * (
                    CASE WHEN m.move_type IN ('out_invoice','in_refund') THEN -1 ELSE 1 END
                    )
                ) as quantity
                FROM account_move_line as l
                LEFT JOIN account_move as m ON l.move_id=m.id
                LEFT JOIN product_product product ON product.id = l.product_id
                LEFT JOIN product_template template ON template.id = product.product_tmpl_id
                LEFT JOIN uom_uom uom_line ON uom_line.id = l.product_uom_id
                LEFT JOIN uom_uom uom_template ON uom_template.id = template.uom_id
                WHERE product_id in %(product_ids)s
                    AND account_id in %(account_ids)s
                    AND m.company_id in %(company_ids)s
                    AND (valuation_area_id in %(valuation_area_ids)s or valuation_area_id is null)
                    AND m.state = 'posted'
                GROUP BY  product_id, valuation_area_id, account_id, m.company_id
           """,
            params,
        )

        res = self.env.cr.dictfetchall()

        for valuation in self:
            valuation.amount = 0
            valuation.debit = 0
            valuation.credit = 0
            valuation.quantity = 0
            for line in res:
                if not line["valuation_area_id"]:
                    line["valuation_area_id"] = False
                if (
                    line["product_id"] == valuation.product_id.id
                    and line["valuation_area_id"] == valuation.valuation_area_id.id
                    and line["account_id"] == valuation.account_id.id
                    and line["company_id"] == valuation.company_id.id
                ):
                    valuation.quantity += line["quantity"]
                    valuation.amount += line["debit"] - line["credit"]
                    valuation.debit += line["debit"]
                    valuation.credit += line["credit"]
                    res.remove(line)

    def recompute_all_amount(self):
        params = {
            "account_ids": tuple(self.env["account.account"].search([("stock_valuation", "=", True)]).ids),
        }
        self.env.cr.execute("DELETE FROM product_valuation WHERE account_id in %(account_ids)s", params)
        self.env.cr.execute(
            """
            INSERT INTO product_valuation
                (product_id, valuation_area_id, account_id, company_id,
                quantity, quantity_in, quantity_out, debit, credit, amount)
            select product_id, valuation_area_id, account_id, company_id,
                        quantity, quantity_in, quantity_out, debit, credit, debit-credit as amount
            FROM (
            SELECT product_id, valuation_area_id, account_id, company_id,
                sum(debit) as debit, sum(credit) as credit,
                sum(
                    quantity * (
                    CASE
                        WHEN move_type ='in_invoice' THEN 1
                        WHEN move_type ='in_refund' THEN -1
                        WHEN move_type IN ('out_invoice','out_refund') THEN 0
                        ELSE
                            CASE WHEN debit > 0 THEN 1 ELSE 0 END
                    END
                    )
                ) as quantity_in,

                sum(
                    quantity * (
                    CASE
                        WHEN move_type ='out_invoice' THEN 1
                        WHEN move_type ='out_refund' THEN -1
                        WHEN move_type IN ('in_invoice','in_refund') THEN 0
                        ELSE CASE WHEN credit > 0 THEN -1 ELSE 0 END
                    END
                    )
                ) as quantity_out,

                sum(
                    quantity * (
                    CASE WHEN move_type IN ('out_invoice','in_refund') THEN -1 ELSE 1 END
                    )
                ) as quantity

            FROM (
                SELECT product_id, valuation_area_id, account_id, m.company_id,
                    debit, credit, move_type,
                    l.quantity / NULLIF(COALESCE(uom_line.factor, 1) / COALESCE(uom_template.factor, 1), 0.0) as quantity
                FROM account_move_line as l
                    LEFT JOIN account_move as m ON l.move_id=m.id
                    LEFT JOIN product_product product ON product.id = l.product_id
                    LEFT JOIN product_template template ON template.id = product.product_tmpl_id
                    LEFT JOIN uom_uom uom_line ON uom_line.id = l.product_uom_id
                    LEFT JOIN uom_uom uom_template ON uom_template.id = template.uom_id
                WHERE
                    account_id in %(account_ids)s
                    AND m.state = 'posted'
                ) as sub
             GROUP BY  product_id, valuation_area_id, account_id, company_id
           ) as a """,
            params,
        )


class ProductValuationHistory(models.Model):
    _name = "product.valuation.history"
    _description = "Product Valuation History"
    _inherit = ["product.valuation"]
    _order = "product_id, date desc"

    year = fields.Char(string="Year", required=True, index=True)
    month = fields.Char(string="Month", required=True, index=True)
    date = fields.Date()

    amount_initial = fields.Monetary("Initial Amount", default=0.0)
    quantity_initial = fields.Float("Initial Quantity", digits="Product Unit of Measure", default=0.0)

    amount_final = fields.Monetary("Final Amount", default=0.0)
    quantity_final = fields.Float("Final Quantity", digits="Product Unit of Measure", default=0.0)

    _sql_constraints = [
        (
            "product_valuation_history_uniq",
            "unique (product_id, valuation_area_id, account_id, company_id, year, month)",
            "Product valuation history must be unique",
        )
    ]

    def get_valuation(self, product_id, valuation_area_id, account_id, date, company_id=False):
        if not company_id:
            company_id = self.env.company.id

        year = date.year
        month = date.month
        domain = [
            ("product_id", "=", product_id),
            ("valuation_area_id", "=", valuation_area_id),
            ("account_id", "=", account_id),
            ("company_id", "=", company_id),
            ("year", "=", year),
            ("month", "=", month),
        ]
        valuation = self.search(domain, limit=1)
        if not valuation:
            valuation = self.create(
                {
                    "product_id": product_id,
                    "valuation_area_id": valuation_area_id,
                    "account_id": account_id,
                    "year": year,
                    "month": month,
                    "company_id": company_id,
                }
            )
        return valuation

    def recompute_amount(self):
        valuation_areas = self.mapped("valuation_area_id")
        products = self.mapped("product_id")
        accounts = self.mapped("account_id")
        companies = self.mapped("company_id")
        domain = [
            ("product_id", "in", products.ids),
            ("account_id", "in", accounts.ids),
            ("company_id", "in", companies.ids),
        ]
        if valuation_areas:
            domain.append(("valuation_area_id", "in", valuation_areas.ids))

        params = {
            "product_ids": tuple(products.ids),
            "account_ids": tuple(accounts.ids),
            "year": tuple(self.mapped("year")),
            "month": tuple(self.mapped("month")),
            "company_ids": tuple(companies.ids),
            "valuation_area_ids": tuple(valuation_areas.ids) or (None,),
        }
        self.env.cr.execute(
            """
            SELECT product_id, valuation_area_id, account_id, m.company_id,
             EXTRACT(YEAR FROM m.date) as year, EXTRACT(MONTH FROM m.date) as month,
                 (date_trunc('month', m.date) + interval '1 month - 1 day')::date as date,
                sum(l.debit) as debit, sum(l.credit) as credit, sum(
                    l.quantity / NULLIF(COALESCE(uom_line.factor, 1) / COALESCE(uom_template.factor, 1), 0.0) * (
                    CASE WHEN m.move_type IN ('out_invoice','in_refund') THEN -1 ELSE 1 END
                    )
                ) as quantity
                FROM account_move_line as l
                LEFT JOIN account_move as m ON l.move_id=m.id
                LEFT JOIN product_product product ON product.id = l.product_id
                LEFT JOIN product_template template ON template.id = product.product_tmpl_id
                LEFT JOIN uom_uom uom_line ON uom_line.id = l.product_uom_id
                LEFT JOIN uom_uom uom_template ON uom_template.id = template.uom_id
                WHERE product_id in %(product_ids)s
                    AND account_id in %(account_ids)s
                    AND m.company_id in %(company_ids)s
                    AND EXTRACT(YEAR FROM m.date)  in %(year)s
                    AND EXTRACT(MONTH FROM m.date) in %(month)s
                    AND (valuation_area_id in %(valuation_area_ids)s or valuation_area_id is null)
                    AND m.state = 'posted'
                GROUP BY  product_id, valuation_area_id, account_id, m.company_id,
                EXTRACT(YEAR FROM m.date), EXTRACT(MONTH FROM m.date),
                (date_trunc('month', m.date) + interval '1 month - 1 day')::date
           """,
            params,
        )

        res = self.env.cr.dictfetchall()

        for valuation in self:
            valuation.amount = 0
            valuation.quantity = 0
            valuation.debit = 0
            valuation.credit = 0
            for line in res:
                if not line["valuation_area_id"]:
                    line["valuation_area_id"] = False
                if (
                    line["product_id"] == valuation.product_id.id
                    and line["valuation_area_id"] == valuation.valuation_area_id.id
                    and line["account_id"] == valuation.account_id.id
                    and line["company_id"] == valuation.company_id.id
                    and line["year"] == valuation.year
                    and line["month"] == valuation.month
                ):
                    valuation.quantity += line["quantity"]
                    valuation.amount += line["debit"] - line["credit"]
                    valuation.debit += line["debit"]
                    valuation.credit += line["credit"]
                    valuation.date = line["date"]
                    res.remove(line)

    def recompute_all_amount(self):
        params = {
            "account_ids": tuple(self.env["account.account"].search([("stock_valuation", "=", True)]).ids),
        }

        if self.env.company.valuation_area_level == "company" and not self.env.company.valuation_area_id:
            _logger.info("Creare zona de evaluare pentru companie.")
            valuation_area = self.env["valuation.area"].create(
                {
                    "name": self.env.company.name,
                    "company_id": self.env.company.id,
                }
            )

            self.env.company.valuation_area_id = valuation_area.id
            params["valuation_area_id"] = valuation_area.id
            _logger.info("Actualizre zona de evaluare pentru notele contabile")
            self.env.cr.execute(
                """
                UPDATE account_move_line SET   valuation_area_id = %(valuation_area_id)s
                where account_id in %(account_ids)s
                """,
                params,
            )

            return

        _logger.info("Stergere linii istoric")
        self.env.cr.execute("DELETE FROM product_valuation_history WHERE account_id in %(account_ids)s", params)
        _logger.info("Calculare linii istoric miscari lunare")
        self.env.cr.execute(
            """
            INSERT INTO product_valuation_history
                (product_id, valuation_area_id, account_id, company_id, year, month, date,
                quantity, quantity_in, quantity_out, debit, credit, amount)
            SELECT product_id, valuation_area_id, account_id, company_id,  year, month, date,
                        quantity, quantity_in, quantity_out, debit, credit, debit-credit as amount
            FROM (
            SELECT product_id, valuation_area_id, account_id, company_id,  year, month, date,
                sum(debit) as debit, sum(credit) as credit,
                sum(
                    quantity * (
                    CASE
                        WHEN move_type ='in_invoice' THEN 1
                        WHEN move_type ='in_refund' THEN -1
                        WHEN move_type IN ('out_invoice','out_refund') THEN 0
                        ELSE
                            CASE WHEN debit > 0 THEN 1 ELSE 0 END
                    END
                    )
                ) as quantity_in,

                sum(
                    quantity * (
                    CASE
                        WHEN move_type ='out_invoice' THEN 1
                        WHEN move_type ='out_refund' THEN -1
                        WHEN move_type IN ('in_invoice','in_refund') THEN 0
                        ELSE CASE WHEN credit > 0 THEN -1 ELSE 0 END
                    END
                    )
                ) as quantity_out,

                sum(
                    quantity * (
                    CASE WHEN move_type IN ('out_invoice','in_refund') THEN -1 ELSE 1 END
                    )
                ) as quantity

            FROM (
                SELECT product_id, valuation_area_id, account_id, m.company_id,
                    debit, credit, move_type,
                    EXTRACT(YEAR FROM m.date) as year, EXTRACT(MONTH FROM m.date) as month,
                    (date_trunc('month', m.date) + interval '1 month - 1 day')::date as date,
                    l.quantity / NULLIF(COALESCE(uom_line.factor, 1) / COALESCE(uom_template.factor, 1), 0.0) as quantity
                FROM account_move_line as l
                    LEFT JOIN account_move as m ON l.move_id=m.id
                    LEFT JOIN product_product product ON product.id = l.product_id
                    LEFT JOIN product_template template ON template.id = product.product_tmpl_id
                    LEFT JOIN uom_uom uom_line ON uom_line.id = l.product_uom_id
                    LEFT JOIN uom_uom uom_template ON uom_template.id = template.uom_id
                WHERE
                    account_id in %(account_ids)s
                    AND m.state = 'posted'
                ) as sub
             GROUP BY  product_id, valuation_area_id, account_id, company_id, year, month, date
           ) as a """,
            params,
        )

        _logger.info("resetare Sold initial si final")
        self.env.cr.execute(
            """
            UPDATE product_valuation_history AS pv
                SET
                    quantity_initial = 0,
                    quantity_final = pv.quantity,
                    amount_initial = 0,
                    amount_final = pv.amount
        """
        )

        # optinere data minima si maxima
        self.env.cr.execute(
            """
            SELECT min(date) as min_date, max(date) as max_date
            FROM product_valuation_history
            """
        )
        res = self.env.cr.dictfetchone()

        params["min_date"] = res["min_date"]
        params["max_date"] = res["max_date"]

        _logger.info("Adaugare linii lipsa")
        self.env.cr.execute(
            """
            drop table if exists calendar_temporal;
            CREATE TEMP TABLE calendar_temporal AS
            SELECT
                (date_trunc('MONTH', generate_series) + INTERVAL '1 MONTH' - INTERVAL '1 day')::DATE AS date
            FROM
                generate_series(%(min_date)s::date, %(max_date)s::date, '1 month'::interval) ;

            INSERT INTO product_valuation_history (product_id, valuation_area_id, account_id, company_id, date, year, month)
            SELECT
                p.product_id,
                v.valuation_area_id,
                a.account_id,
                comp.company_id,
                c.date,
                date_part('year', c.date) AS year,
                date_part('month', c.date) AS month
            FROM
                calendar_temporal c
            CROSS JOIN (SELECT DISTINCT product_id FROM product_valuation_history) p
            CROSS JOIN (SELECT DISTINCT valuation_area_id FROM product_valuation_history) v
            CROSS JOIN (SELECT DISTINCT account_id FROM product_valuation_history) a
            CROSS JOIN (SELECT DISTINCT company_id FROM product_valuation_history) comp
            WHERE NOT EXISTS (
                SELECT 1
                FROM product_valuation_history pv
                WHERE
                    pv.product_id = p.product_id AND
                    pv.valuation_area_id = v.valuation_area_id AND
                    pv.account_id = a.account_id AND
                    pv.company_id = comp.company_id AND
                    pv.date = c.date
            )

            """,
            params,
        )

        _logger.info("Calculare sold initial si final")
        self.env.cr.execute(
            """
                UPDATE product_valuation_history AS pv
                SET
                    quantity_initial =  cv.quantity_final - pv.quantity,
                    quantity_final = cv.quantity_final,
                    amount_initial = cv.amount_final - pv.amount,
                    amount_final =  cv.amount_final
                FROM (
                    SELECT
                        product_id,
                        valuation_area_id,
                        account_id,
                        company_id,
                        date,
--                        COALESCE(LAG(quantity_final) OVER (
--                            PARTITION BY product_id, valuation_area_id, account_id, company_id
--                             ORDER BY date), 0) AS quantity_initial,
--                        COALESCE(LAG(amount_final) OVER (
--                            PARTITION BY product_id, valuation_area_id, account_id, company_id
--                            ORDER BY date), 0)  AS amount_initial,
                        SUM(quantity) OVER (
                            PARTITION BY product_id, valuation_area_id, account_id, company_id
                             ORDER BY date) AS quantity_final,
                        SUM(amount) OVER (
                            PARTITION BY product_id, valuation_area_id, account_id, company_id
                            ORDER BY date) AS amount_final
                    FROM
                        product_valuation_history
                ) AS cv
                WHERE
                    pv.product_id = cv.product_id AND
                    pv.account_id = cv.account_id AND
                    pv.valuation_area_id = cv.valuation_area_id AND
                    pv.company_id = cv.company_id AND
                    pv.date = cv.date

            """
        )

        _logger.info("FINALIZARE CALCULARE ISTORIC VALORI")
