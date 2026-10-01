"""insert_missing_reps must leave every section pointing at its REAL rows.

2026-10-01, Luke Baldwin's brand-new B2B churn tab: one rep row per section,
three new reps inserted into each of five sections in one run. The re-resolve
compared rows an earlier insert had already shifted against the original
anchors, so from the third section down every header was shifted twice, the
sortRange spans crossed section borders, and the tab came out scrambled.

    python -m unittest automations.new_internet_churn.test_insert_missing_reps
"""
import unittest
from unittest import mock

from automations.new_internet_churn import fill


def _tab(n_sections=5, gap=3):
    """Luke's layout: header, avg, 'Rep', ONE rep row, `gap` blank rows."""
    sections, row = {}, 2
    for k in range(n_sections):
        sections[f"p{k}"] = {
            "header_row": row, "office_avg_row": row + 1,
            "rep_header_row": row + 2,
            "rep_rows": {"luke baldwin": row + 3},
        }
        row += 4 + gap
    return sections


def _expected(n_sections=5, gap=3, added=3):
    out, row = {}, 2
    for k in range(n_sections):
        out[f"p{k}"] = (row, row + 1, row + 2,
                        {"luke baldwin": row + 3,
                         **{n: row + 4 + i for i, n in enumerate(
                             ["adrian sarabia", "cruz venegas", "david pisikian"])}})
        row += 4 + added + gap
    return out


class InsertMissingRepsTest(unittest.TestCase):
    def test_every_section_points_at_its_real_rows(self):
        sections = _tab()
        pct = {f"p{k}": {"pct": "1.0%"} for k in range(5)}
        parsed = {"reps": {n: dict(pct) for n in (
            "Luke Baldwin", "Cruz Venegas", "David Pisikian", "Adrian Sarabia")}}
        ws = mock.Mock(id=1, title="t")
        with mock.patch.object(fill, "reconcile_parsed_to_roster",
                               lambda *a, **k: {}), \
             mock.patch.object(fill.time, "sleep", lambda *_: None):
            added = fill.insert_missing_reps(ws, sections, parsed,
                                             logfn=lambda *_: None)
        self.assertEqual(sorted(added), [f"p{k}" for k in range(5)])
        for p, (hdr, avg, rep_hdr, reps) in _expected().items():
            s = sections[p]
            self.assertEqual((s["header_row"], s["office_avg_row"],
                              s["rep_header_row"]), (hdr, avg, rep_hdr), p)
            self.assertEqual(s["rep_rows"], reps, p)

        # The names went to the same rows the map now points at.
        written = {d["range"].split("!A")[1]: d["values"][0][0]
                   for d in ws.spreadsheet.values_batch_update
                   .call_args.args[0]["data"]}
        for p, (_h, _a, _r, reps) in _expected().items():
            for name, row in reps.items():
                if name != "luke baldwin":
                    self.assertEqual(written[str(row)].lower(), name, (p, row))


if __name__ == "__main__":
    unittest.main()
