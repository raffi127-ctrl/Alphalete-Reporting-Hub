import datetime as dt
import unittest

from automations.first_round_scorecards import office_post as op

DAY = dt.date(2026, 10, 6)


def row(interviewer, office, score, time="09:00", date="2026-10-06", **kw):
    return {"interviewer": interviewer, "office": office, "score": score, "time": time,
            "date": date, "doc": kw.get("doc", "D1"), "flags": kw.get("flags", []),
            "missed": kw.get("missed", []), "coaching": kw.get("coaching", [])}


class OfficePostTest(unittest.TestCase):
    def test_raf_funnels_are_one_office_post(self):
        rows = [row("Ana", "Rafael Hidalgo", 60), row("Bo", "Raf Hidalgo 2nd funnel", 40),
                row("Cy", "Raf Hidalgo 3rd funnel", 50)]
        posts = op.posts(rows, DAY)
        self.assertEqual([(o, c) for o, c, _ in posts], [("Rafael Hidalgo", "C0AUAS88FGW")])
        self.assertIn("Office average: *50/100* 🔵", posts[0][2])

    def test_only_that_day_and_rows_with_an_office(self):
        rows = [row("Ana", "Jairo Ruiz", 60), row("Ana", "Jairo Ruiz", 10, date="2026-10-05"),
                row("Zed", "", 30)]
        posts = op.posts(rows, DAY)
        self.assertEqual(len(posts), 1)
        self.assertIn("1 interview\n", posts[0][2] + "\n")

    def test_text_has_score_flags_feedback_and_links(self):
        rows = [row("Gonzalo", "Jairo Ruiz", 45, time="10:31", doc="X1",
                    flags=["pay different from the script"], missed=["wrap-up script"],
                    coaching=["Explain the pay. More detail.", "Say the wrap-up."]),
                row("Gonzalo", "Jairo Ruiz", 55, time="13:01", doc="X2",
                    coaching=["Latest tip. More.", "Second tip."])]
        text = op.office_text("Jairo Ruiz", rows, DAY)
        self.assertIn("Jairo Ruiz's office — Tue 10/6", text)
        self.assertIn("*Gonzalo* — 50/100 🔵", text)
        self.assertIn("🚩 Red flags: pay different from the script ×1", text)
        self.assertIn("❌ Most missed: wrap-up script ×1", text)
        self.assertIn("• Latest tip.", text)          # the latest interview's tips
        self.assertNotIn("Explain the pay", text)
        self.assertIn("<https://docs.google.com/document/d/X1/edit|10:31 AM>", text)

    def test_colors_match_the_board(self):
        self.assertEqual((op.emoji(49), op.emoji(50), op.emoji(51)), ("🔴", "🔵", "🟢"))

    def test_off_until_the_sample_is_approved(self):
        self.assertFalse(op.LIVE)


if __name__ == "__main__":
    unittest.main()
