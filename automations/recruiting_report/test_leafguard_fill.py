"""python -m unittest automations.recruiting_report.test_leafguard_fill"""
import unittest

from automations.recruiting_report.leafguard_fill import compute_week, _label_rows

# Shapes copied from the real .csv exports (11/25/2026), trailing spaces and
# Spanish subtotal rows included.
LCM = """ Closer Rep,Closer ICD,Market,Nombres de medidas,Valores de medidas
Todo,Spencer Brown,Sacramento,Gross Close,3
Luong Lam,Spencer Brown,Sacramento,IL ,8
Luong Lam,Spencer Brown,Sacramento,Demos  ,6
Luong Lam,Spencer Brown,Sacramento,Gross Close,1
Luong Lam,Spencer Brown,Sacramento,Gross Sales $,"13,000"
Sahil Chand,Spencer Brown,Sacramento,Gross Close,2
Kyle Polhill,Adam Cole,Tampa,Gross Close,5
"""
CRST = """ Closer Rep,Market,Nombres de medidas,Valores de medidas
Luong Lam,Sacramento,Gross Close,1
Luong Lam,Sacramento,Valid Sales,1
Luong Lam,Sacramento,Valid Sales $,"9,800"
Sahil Chand,Sacramento,Valid Sales,0
Kyle Polhill,Tampa,Valid Sales,4
Todo,Todo,Valid Sales,5
"""
LG = """Lead Rep ICD ,Lead Rep Name,Nombres de medidas,Valores de medidas
Spencer Brown,Hatem Atta,Raw leads ,9
Spencer Brown,Hatem Atta,Issued leads,3
Spencer Brown,Hatem Atta,Demos,2
Spencer Brown,Derek Pliego,Raw leads ,4
Spencer Brown,Derek Pliego,Demos,2
Spencer Brown,Derek Pliego,Gross Sales $,"33,300"
Spencer Brown,Total,Raw leads ,13
Spencer Brown,Total,Demos,4
Adam Cole,Kyle Polhill,Raw leads ,13
"""


class ComputeWeek(unittest.TestCase):
    def test_numbers(self):
        self.assertEqual(compute_week(LCM, CRST, LG), {
            "LeafGuard Total Sales": 3,   # 1 + 2, Todo subtotal skipped
            "LeafGuard Valid Sales": 1,   # Spencer's closers only
            "LeafGuard Leads": 13,        # Raw leads, Total row skipped
            "LeafGuard Demos": 4,
        })

    def test_empty_week_is_zero(self):
        h = "a,b,c,d,e\n"
        self.assertEqual(set(compute_week(h, h, h).values()), {0})


class Labels(unittest.TestCase):
    def test_first_match_by_column_b(self):
        rows = _label_rows([["OFFICE GOALS", "OPT"], ["", "Badged % "],
                            ["", "badged %"]])
        self.assertEqual(rows["badged %"], 2)


if __name__ == "__main__":
    unittest.main()
