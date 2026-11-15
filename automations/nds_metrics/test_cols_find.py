# -*- coding: utf-8 -*-
"""Cols.find lands on the tightest header (2026-11-15: a new 'Order date to
Install Date Days' field on the export stole 'order date')."""
import unittest

from automations.nds_metrics.run import Cols

HEADER = ['Auto Bill Pay', 'cl.DD Date', 'Credit Score Category', 'Customer Name', 'Customer Zip Simple',
          'CX Address', 'Device Description', 'DTR Active Date', 'DTR Status', 'icd.Lead Rep ID', 'IF/OOF',
          'LeadID Match Code', 'Measure Names', 'Order date to Install Date Days', 'Order Status',
          'Owner & Office', 'Package', 'Phone Model', 'Product Type (Broken Out)', 'Rep',
          'Rep Tier Bonus Status', 'rep.Rep Number', 'sp.Generic SSN', 'sp.Order Date (copy)',
          'sp.SPM Number', 'spe.Account BAN', 'SPE.DTR Current Due Date (date)', 'spe.dtr Order Type',
          'spe.dtr Posted Date', 'spe.Install Date', 'spe.Name', 'spe.Port Carrier', 'spe.Status', 'spe.TN',
          'spe.TN Type', 'spe.Wireless Type', 'Status Date', 'Tech Install', 'Wireless Installment Plan',
          'Past Install Date', 'Voice Line Count', 'Measure Values']


class Find(unittest.TestCase):
    def test_order_date_lands_on_the_real_column(self):
        cols = Cols(HEADER)
        self.assertEqual(cols.header[cols.need("order date", "sp.order date")], "sp.Order Date (copy)")
        self.assertEqual(cols.header[cols.find("sp.order date (copy)", "sp.order date", "order date")], "sp.Order Date (copy)")

    def test_the_other_lookups_are_unchanged(self):
        cols = Cols(HEADER)
        for cands, want in ((("rep",), "Rep"), (("owner", "owner name", "owner & office", "owner"), "Owner & Office"),
                            (("dtr status", "spe.status"), "DTR Status"), (("package",), "Package"),
                            (("device description", "spe.phone", "device"), "Device Description"),
                            (("spe.tn type", "tn type"), "spe.TN Type"),
                            (("product type (broken out)", "product type"), "Product Type (Broken Out)"),
                            (("spe.wireless type", "wireless type"), "spe.Wireless Type"),
                            (("sp.spm number", "spm number"), "sp.SPM Number"),
                            (("wireless installment plan",), "Wireless Installment Plan"), (("if/oof",), "IF/OOF"),
                            (("auto bill pay",), "Auto Bill Pay"), (("measure names",), "Measure Names"),
                            (("dtr active date", "activatoin date", "dtr first available"), "DTR Active Date"),
                            (("customer name",), "Customer Name"), (("ported from", "port"), "spe.Port Carrier")):
            self.assertEqual(cols.header[cols.find(*cands)], want, cands)
        self.assertIsNone(cols.find("ported from"))


if __name__ == "__main__":
    unittest.main()
