"""El orden de las cajas de delta: que ordene por col C descendente, que NO
toque la col A (la cadena de ranks) y que cubra el ancho entero de la caja
(hasta el Delta del ultimo dia, o sea el domingo).

Pedido de Eve, 2026-09-02: las cajas tienen que quedar ordenadas todos los dias.
Hasta ese dia no las ordenaba nadie — `sort.py` las excluye a proposito porque
escribirlas como valores congela sus formulas ([[2026-08-25]])."""
import unittest

from automations.org_sales_board import delta_sort as DS

DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday",
        "Sunday"]


def _box(title, rows):
    """Una caja con la forma real: titulo, sub-encabezado con los tripletes
    This week / Last week / Delta por dia, filas de rep, y la fila de totales
    que corta el bloque."""
    head = [title, "", "Total for week", "", ""]
    sub = ["NEW INTERNET UNITS", "", "Total this week", "Last week", "Delta"]
    for _d in DAYS:
        head += ["", "", ""]
        sub += ["This week", "Last week", "Delta"]
    out = [head, sub]
    for i, (name, tot) in enumerate(rows, start=1):
        out.append([str(i), name, str(tot), "0", "0"] + ["0"] * 21)
    out.append(["Captainship", "", "0", "0", "0"] + ["0"] * 21)
    return out


class DeltaSort(unittest.TestCase):
    def setUp(self):
        self.grid = ([[""] * 26] * 3 + _box("Pat's Captainship", [
            ("Alex Touati", 10), ("Pat Thompson", 53), ("Gabe Perez", 26)]))
        self.reqs = DS.plan_delta_sorts(self.grid, sheet_id=7)

    def test_one_request_per_box(self):
        self.assertEqual(len(self.reqs), 1)
        self.assertEqual(self.reqs[0]["sortRange"]["range"]["sheetId"], 7)

    def test_col_a_stays_out_of_the_range(self):
        """La col A es la cadena de ranks: 1..N tiene que quedarse quieta
        mientras las filas se mueven abajo."""
        rng = self.reqs[0]["sortRange"]["range"]
        self.assertEqual(rng["startColumnIndex"], 1)      # col B

    def test_the_range_reaches_sundays_delta(self):
        """Cortar antes deja el sabado y el domingo sin mover, que es como se
        desalinea una caja sin que ningun total falle."""
        rng = self.reqs[0]["sortRange"]["range"]
        self.assertEqual(rng["endColumnIndex"], 26)       # col Z

    def test_only_the_rep_rows_move(self):
        """Ni el sub-encabezado ni la fila de totales entran al rango."""
        rng = self.reqs[0]["sortRange"]["range"]
        self.assertEqual(rng["startRowIndex"], 5)         # 0-based: 1a fila rep
        self.assertEqual(rng["endRowIndex"], 8)           # exclusivo: 3 filas

    def test_sorts_by_col_c_desc_then_name(self):
        specs = self.reqs[0]["sortRange"]["sortSpecs"]
        self.assertEqual(specs[0], {"dimensionIndex": 2,
                                    "sortOrder": "DESCENDING"})
        self.assertEqual(specs[1], {"dimensionIndex": 1,
                                    "sortOrder": "ASCENDING"})

    def test_a_one_row_box_is_left_alone(self):
        """Una caja de una sola fila no tiene nada que ordenar; pedir un
        sortRange de un renglon es ruido."""
        grid = _box("Solo", [("Uno", 5)])
        self.assertEqual(DS.plan_delta_sorts(grid, 7), [])

    def test_every_box_on_the_tab_gets_one(self):
        grid = (_box("Pat's Captainship", [("A", 1), ("B", 2)])
                + [[""] * 26]
                + _box("Jess's Captainship", [("C", 3), ("D", 4)]))
        self.assertEqual(len(DS.plan_delta_sorts(grid, 7)), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
