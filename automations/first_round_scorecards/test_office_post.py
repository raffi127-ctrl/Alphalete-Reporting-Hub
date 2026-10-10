import datetime as dt
import unittest

from automations.first_round_scorecards import office_post as op

DAY = dt.date(2026, 10, 6)


def row(interviewer, office, score, time="09:00", date="2026-10-06", **kw):
    return {"interviewer": interviewer, "office": office, "score": score, "time": time,
            "date": date, "doc": kw.get("doc", "D1"), "flags": kw.get("flags", []),
            "missed": kw.get("missed", []), "coaching": kw.get("coaching", [])}


class OfficePostTest(unittest.TestCase):
    def test_raf_funnels_are_one_office_thread(self):
        rows = [row("Ana", "Rafael Hidalgo", 60), row("Bo", "Raf Hidalgo 2nd funnel", 40),
                row("Cy", "Raf Hidalgo 3rd funnel", 50)]
        posts = op.posts(rows, DAY)
        self.assertEqual([(o, c) for o, c, _, _ in posts], [("Rafael Hidalgo", "C0AUAS88FGW")])
        self.assertEqual(posts[0][3][0][0], op.OVERVIEW)
        self.assertIn("Office average: *50/100* 🔵", posts[0][3][0][1])

    def test_parent_is_the_title_alone(self):
        # Rafael, 10/9: "less verbiage on the title of the thread, and more in the thread"
        day = dt.date(2026, 10, 9)
        _, _, head, _ = op.posts([row("Ana", "Rafael Hidalgo", 60, date="2026-10-09")], day)[0]
        self.assertEqual(head,"📋 *1st Round Scorecards — Rafael Hidalgo's office — Fri 10/9*")

    def test_lowest_score_first_unnamed_zoom_last(self):
        rows = [row("Ana", "Jairo Ruiz", 80), row("ZOOM 19", "Jairo Ruiz", 10),
                row("Bo", "Jairo Ruiz", 30), row("Cy", "Jairo Ruiz", 55)]
        _, _, head, replies = op.posts(rows, DAY)[0]
        self.assertEqual([n for n, _ in replies], [op.OVERVIEW, "Bo", "Cy", "Ana", "ZOOM 19"])
        self.assertTrue(replies[0][1].endswith(
            "\n\n🔴  Bo — *30*\n🟢  Cy — *55*\n🟢  Ana — *80*\n🔴  ZOOM 19 — *10*"))

    def test_each_reply_starts_with_a_divider(self):
        _, _, _, replies = op.posts([row("Ana", "Jairo Ruiz", 80), row("Bo", "Jairo Ruiz", 30)], DAY)[0]
        self.assertTrue(all(t.startswith(op.DIVIDER + "\n*") for _, t in replies[1:]))

    def test_only_that_day_and_rows_with_an_office(self):
        rows = [row("Ana", "Jairo Ruiz", 60), row("Ana", "Jairo Ruiz", 10, date="2026-10-05"),
                row("Zed", "", 30)]
        posts = op.posts(rows, DAY)
        self.assertEqual(len(posts), 1)
        self.assertIn("1 interview\n", posts[0][3][0][1])

    def test_reply_has_score_flags_feedback_and_links(self):
        rows = [row("Gonzalo", "Jairo Ruiz", 45, time="10:31", doc="X1",
                    flags=["pay different from the script"], missed=["wrap-up script"],
                    coaching=["Explain the pay. More detail.", "Say the wrap-up."]),
                row("Gonzalo", "Jairo Ruiz", 55, time="13:01", doc="X2",
                    coaching=["Latest tip. More.", "Second tip."])]
        head = op.head_text("Jairo Ruiz", DAY)
        self.assertIn("Jairo Ruiz's office — Tue 10/6", head)
        text = op.person_text("Gonzalo", 50, rows)
        self.assertIn("*Gonzalo* — 50/100 🔵", text)
        # spaced out: a blank line between sections and between the 2 tips (Carlos, 10/9)
        self.assertIn("\n\n🚩 *Red flags*\n• pay different from the script ×1\n\n"
                      "❌ *Most missed*\n• wrap-up script ×1\n\n"
                      "💡 *Feedback*\n• Latest tip.\n\n• Second tip.\n\n📄 *Full audits:*", text)
        self.assertNotIn("Explain the pay", text)
        self.assertIn("<https://docs.google.com/document/d/X1/edit|10:31 AM>", text)

    def test_colors_match_the_board(self):
        self.assertEqual((op.emoji(49), op.emoji(50), op.emoji(51)), ("🔴", "🔵", "🟢"))

    def test_sample_marks_cover_both_formats(self):
        self.assertTrue("📋 *1st Round Scorecard — X".startswith(op.SAMPLE_MARKS))
        self.assertTrue(op.head_text("X", DAY).startswith(op.SAMPLE_MARKS))

    def test_summary_groups_everyone_by_color_lowest_first(self):
        rows = [row("Ana", "Jairo Ruiz", 80), row("Bo", "Blue Mendoza", 30),
                row("Cy", "Raf Hidalgo 2nd funnel", 50), row("Di", "", 45),
                row("Ed", "Ellen Dent", 60, date="2026-10-05")]
        text = op.summary_text(rows, DAY)
        self.assertIn("📊 *1st Round Summary — Tue 10/6*", text)
        self.assertNotIn("Ed", text)                       # another day
        red, blue, green = (text.index("🔴 *Under 50* (2)"), text.index("🔵 *50* (1)"),
                            text.index("🟢 *Over 50* (1)"))
        self.assertLess(red, blue)
        self.assertLess(blue, green)
        self.assertLess(text.index("*Bo* 30 · Blue Mendoza"), text.index("*Di* 45 · 1 interview"))
        self.assertIn("*Cy* 50 · Rafael Hidalgo", text)
        self.assertEqual(op.summary_text(rows, dt.date(2026, 10, 9)), "")

    def test_live_since_the_sample_was_approved(self):
        self.assertTrue(op.LIVE)

    def test_restyle_edits_lucys_thread_in_place(self):
        rows = [row("Ana", "Carlos Hidalgo", 60), row("Bo", "Carlos Hidalgo", 40)]
        head = op.head_text("Carlos Hidalgo", DAY)
        # Slack returns the emoji as a shortcode
        old_head = head.split("\n")[0].replace("📋", ":clipboard:") + "\nOffice average: *50/100* 🔵"

        class Fake:
            def __init__(self):
                self.updates = []

            def auth_test(self):
                return {"user_id": "LUCY"}

            def conversations_history(self, **kw):
                return {"messages": [{"user": "LUCY", "ts": "1.0", "text": old_head},
                                     {"user": "CARLOS", "ts": "2.0", "text": old_head}]}

            def conversations_replies(self, **kw):
                return {"messages": [{"ts": "1.0"},
                                     {"user": "LUCY", "ts": "1.1", "text": op.DIVIDER + "\n*Bo* — 40/100 🔴"},
                                     {"user": "CARLOS", "ts": "1.2", "text": "*Ana* — great"}]}

            def chat_update(self, **kw):
                self.updates.append((kw["ts"], kw["text"]))

            def chat_postMessage(self, **kw):
                raise AssertionError("restyle never posts")

        fake = Fake()
        orig, op._client, op.PAUSE_S = op._client, (lambda: fake), 0
        try:
            self.assertEqual(op.restyle(rows, DAY, "Carlos Hidalgo"), 0)
        finally:
            op._client = orig
        self.assertEqual([ts for ts, _ in fake.updates], ["1.0", "1.1"])   # never Carlos's own
        self.assertEqual(fake.updates[0][1], head)
        # a thread from before 10/9: the overview goes on top of its first reply
        self.assertEqual(fake.updates[1][1], op.overview_text(rows) + "\n\n"
                         + op.person_text("Bo", 40, [rows[1]]))

    def test_restyle_office_from_one_word(self):
        offices = ["Carlos Hidalgo", "Cody Cannon"]
        self.assertEqual(op.find_office("carlos", offices), "Carlos Hidalgo")
        self.assertEqual(op.find_office("Carlos-Hidalgo", offices), "Carlos Hidalgo")
        with self.assertRaises(SystemExit):
            op.find_office("c", offices)

    def test_restyle_all_goes_on_after_a_failure_and_skips_no_channel(self):
        rows = [row("Ana", "Carlos Hidalgo", 60), row("Bo", "Cody Cannon", 40),
                row("Cy", "Nowhere Office", 50)]
        seen = []

        def fake(rows_, day, office, **kw):
            seen.append(office)
            if office == "Carlos Hidalgo":
                raise RuntimeError("slack down")
            return 0

        orig, op.restyle = op.restyle, fake
        try:
            self.assertEqual(op.restyle_all(rows, DAY), 1)
        finally:
            op.restyle = orig
        self.assertEqual(seen, ["Carlos Hidalgo", "Cody Cannon"])


if __name__ == "__main__":
    unittest.main()
