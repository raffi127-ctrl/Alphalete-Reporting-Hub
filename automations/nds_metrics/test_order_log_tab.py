import datetime as dt
import unittest

from automations.nds_metrics import order_log_tab as T

TODAY = dt.date(2026, 10, 29)


def line(**kw):
    base = {"rep": "YAHIR LOPEZ", "customer": "JOHN DOE", "order_date": "10/24/2026",
            "dsi": "DSI123", "wireless_order": "WO555", "ban": "BAN9", "line_no": "1",
            "line_type": "New", "device": "945-392-8474", "line_number": "Smartphone",
            "line_phone": "iPhone 16", "plan": "Unlimited",
            "line_status": "Shipped", "ship_date": "10/25/2026", "delivered": "", "port_status": ""}
    base.update(kw)
    return base


class Rows(unittest.TestCase):
    def test_row_shape_and_week_ending(self):
        r = T.line_row(line(), "10/29/2026")
        self.assertEqual(len(r), len(T.HEADERS))
        self.assertEqual(r[T._COL["Week Ending"]], "10/25/2026")     # Sat 10/24 -> Sun 10/25
        self.assertEqual(r[T._COL["Rep"]], "Yahir Lopez")
        self.assertEqual(r[T._COL["Last Updated"]], "10/29/2026")
        self.assertEqual(r[T._COL["Notes"]], "")
        self.assertEqual(r[T._COL["Being worked on"]], "")
        self.assertEqual(r[T._COL["Delivered Message Sent"]], "")
        self.assertEqual(T.HEADERS[T._COL["Notes"] - 1], "Taylor's Notes")        # 11/17 pm: to the LEFT of Notes
        self.assertEqual(T.HEADERS[T._COL["Order Date"] + 1], "Last Updated")    # 11/17 pm: right after Order Date (11/27: first of the date fold)
        self.assertEqual(T.HEADERS[T._COL["Being worked on"] + 1], "Delivered Message Sent")
        self.assertEqual(T.HEADERS[T._COL["Delivered Message Sent"] + 1], "Shipping Status")  # 11/12 pm: carrier word, left of the notes
        self.assertEqual(T.HEADERS[T._COL["Shipping Status"] + 1], "Shipping Notes")
        self.assertEqual(T.HEADERS[T._COL["Ship Date"] + 1], "Delivered")
        self.assertEqual(T.HEADERS[1], "Pay Period")                  # 11/11 pm: column B
        self.assertEqual(r[T._COL["Pay Period"]], "Pending")          # Shipped, no activation date -> Pending
        self.assertEqual(T.HEADERS[T._COL["Delivered"] + 1], "Activation Date")   # 11/11: right after Delivered
        self.assertEqual(r[T._COL["Phone #"]], "945-392-8474")        # the feed's "device" = Line Number cell
        self.assertEqual(r[T._COL["Device"]], "iPhone 16")            # the model, feed's "line_phone"
        self.assertEqual(r[T._COL["Plan"]], "Unlimited")
        self.assertEqual(r[T._COL["Zip"]], "")                        # no index given -> blank
        # 11/17: the customer-detail group sits together, folded beside Customer;
        # 11/17 evening: Line Status just left of Customer, Device just right of
        # it, both in view -- the group starts after Device
        c = T._COL["Customer"]
        self.assertEqual(T.HEADERS[c - 2:c + 2], ("Line", "Line Status", "Customer", "Device"))
        self.assertEqual(T.HEADERS[c + 2:c + 10], ("Email", "Zip", "DSI #", "Wireless Order #", "BAN", "Phone #",
                                                   "Type", "Plan"))
        self.assertEqual(T.HEADERS[c + 10], "Taylor's Notes")                  # 11/27: the dates moved left
        # 11/19: Order Date and Last Updated sit left of Rep, right after Pay Period;
        # 11/27: the other four dates join Last Updated there, folded
        self.assertEqual(T.HEADERS[:4], ("Week Ending", "Pay Period", "Order Date", "Last Updated"))
        self.assertEqual(T.HEADERS[8], "Rep")
        self.assertEqual(T.HEADERS[-1], "Port Status")                           # 11/17 pm: moved to the very end
        self.assertEqual(T.HEADERS[T._COL["Activation Date"] + 1], "Disconnect Date")
        self.assertEqual(r[T._COL["Disconnect Date"]], "")
        self.assertEqual(r[T._COL["Taylor's Notes"]], "")
        self.assertEqual((r[T._COL["DSI #"]], r[T._COL["Wireless Order #"]], r[T._COL["BAN"]], r[T._COL["Line"]],
                          r[T._COL["Type"]]), ("DSI123", "WO555", "BAN9", "1", "New"))
        self.assertEqual(r[T._COL["Customer"]], "John Doe")
        self.assertEqual(r[T._COL["Order Date"]], "10/24/2026")

    def test_zip_from_the_export_by_phone_then_ban_then_dsi(self):
        hdr = ["Owner & Office", "Customer Name", "Customer Zip Simple", "spe.TN",
               "spe.Account BAN", "sp.SPM Number", "Measure Names"]
        rows = [["CARLOS HIDALGO - X", "JOHN D", "75060", "9453928474", "BAN9", "DSI123", "Unit Count"],
                ["CARLOS HIDALGO - X", "JOHN D", "75060", "9453928474", "BAN9", "DSI123", "Sales (All)"],
                ["CARLOS HIDALGO - X", "ANA R", "76017", "2145550199", "BAN7", "DSI777", "Unit Count"]]
        zi = T.ZipIndex.from_rows(hdr, rows)
        self.assertEqual(len(zi), 2)
        self.assertEqual(zi.for_line(line()), "75060")                           # by phone
        self.assertEqual(zi.for_line(line(device="000-000-0000")), "75060")      # by BAN
        self.assertEqual(zi.for_line(line(device="000-000-0000", ban="")), "75060")   # by DSI
        self.assertEqual(zi.for_line(line(device="", ban="", dsi="")), "")
        r = T.line_row(line(), "x", zi.for_line)
        self.assertEqual(r[T._COL["Zip"]], "75060")
        self.assertEqual(r[T._COL["Phone #"]], "945-392-8474")
        self.assertEqual(r[T._COL["Device"]], "iPhone 16")
        with self.assertRaises(RuntimeError):
            T.ZipIndex.from_rows(["Customer Name", "spe.TN"], [["X", "1"]])

    def test_zip_kept_when_today_cannot_place_the_line(self):
        first = T.merge([], [line()], today=TODAY, zip_of=lambda l: "75060")
        self.assertEqual(first["rows"][0][T._COL["Zip"]], "75060")
        second = T.merge(first["rows"], [line()], today=TODAY + dt.timedelta(days=1), zip_of=None)
        self.assertEqual(second["rows"][0][T._COL["Zip"]], "75060")
        self.assertEqual(second["changed"], 0)                         # a zip is not a state change
        third = T.merge(second["rows"], [line()], today=TODAY + dt.timedelta(days=2),
                        zip_of=lambda l: "76017")
        self.assertEqual(third["rows"][0][T._COL["Zip"]], "76017")
        self.assertEqual(third["changed"], 0)

    def test_carried_row_without_a_zip_is_looked_up_by_its_own_cells(self):
        # a line the feed has forgotten: on the tab, no zip yet (the column is
        # new), absent from today's lines -> filled through zip_lookup
        kept = T.line_row(line(wireless_order="WOGONE", line_no="1"), "10/20/2026")
        self.assertEqual(kept[T._COL["Zip"]], "")
        seen = []
        def lookup(phone, ban, dsi):
            seen.append((phone, ban, dsi))
            return "75060" if phone == "945-392-8474" else ""
        out = T.merge([kept], [line(line_no="2")], today=TODAY, zip_of=lambda l: "76017",
                      zip_lookup=lookup)
        by_key = {T._key(x): x for x in out["rows"]}
        self.assertEqual(by_key[("wo", "wogone", "1")][T._COL["Zip"]], "75060")
        self.assertEqual(by_key[("wo", "wo555", "2")][T._COL["Zip"]], "76017")
        self.assertEqual(seen, [("945-392-8474", "BAN9", "DSI123")])
        # a row that already has a zip is left alone (no lookup)
        again = T.merge(out["rows"], [], today=TODAY, zip_lookup=lambda *a: "00000")
        self.assertEqual({x[T._COL["Zip"]] for x in again["rows"]}, {"75060", "76017"})

    def test_old_tab_layout_remaps_by_header(self):
        # the live tab before 11/9: no "Phone #", "Device" held the number, column S = Delivered Message Sent
        old_hdr = ["Week Ending", "Rep", "Customer", "Order Date", "DSI #", "Wireless Order #", "BAN",
                   "Line", "Type", "Device", "Plan", "Line Status", "Ship Date", "Delivered", "Port Status",
                   "Last Updated", "Notes", "Being worked on", "Delivered Message Sent"]
        old_row = ["10/25/2026", "Yahir Lopez", "John Doe", "10/24/2026", "DSI123", "WO555", "BAN9",
                   "2", "Port", "945-392-8474", "Unlimited", "Shipped", "10/25/2026", "", "",
                   "10/29/2026", "called 10/28", "Yes", "Yes"]
        r = T.remap(old_row, old_hdr)
        self.assertEqual(len(r), len(T.HEADERS))
        self.assertEqual(r[T._COL["Phone #"]], "945-392-8474")
        self.assertEqual(r[T._COL["Device"]], "")
        self.assertEqual(r[T._COL["Zip"]], "")                          # the live tab before 11/10 has no Zip
        self.assertEqual(r[T._COL["Notes"]], "called 10/28")
        self.assertEqual(r[T._COL["Being worked on"]], "Yes")
        self.assertEqual(r[T._COL["Delivered Message Sent"]], "Yes")
        # through merge: line 2 absent from today's feed is kept with its typed columns in place
        out = T.merge([old_row], [line()], today=TODAY, existing_header=old_hdr)
        by_key = {T._key(x): x for x in out["rows"]}
        kept = by_key[("wo", "wo555", "2")]
        self.assertEqual(kept[T._COL["Delivered Message Sent"]], "Yes")
        self.assertEqual(kept[T._COL["Notes"]], "called 10/28")
        self.assertEqual(kept[T._COL["Phone #"]], "945-392-8474")
        # today's header round-trips unchanged
        fresh = out["rows"][0]
        self.assertEqual(T.remap(fresh, T.HEADERS), list(fresh))

    def test_html_entities_are_unescaped(self):
        r = T.line_row(line(plan="AT&amp;T Premium", customer="O&#39;BRIEN"), "x")
        self.assertEqual(r[T._COL["Plan"]], "AT&T Premium")
        self.assertEqual(r[T._COL["Customer"]], "O'Brien")

    def test_key_fallbacks(self):
        self.assertEqual(T._key(T.line_row(line(), "x"))[0], "wo")
        self.assertEqual(T._key(T.line_row(line(wireless_order=""), "x"))[0], "dsi")
        self.assertEqual(T._key(T.line_row(line(wireless_order="", dsi=""), "x"))[0], "cust")


class Usable(unittest.TestCase):
    def test_headerless_feed_is_refused(self):
        bare = [{"line_no": "1", "line_type": "New", "line_status": "Shipped"}] * 5
        self.assertFalse(T.usable([], bare))
        self.assertFalse(T.usable([{"customer": "X"}], bare))
        self.assertTrue(T.usable([{"customer": "X"}], [line(), line(line_no="2")]))


class Merge(unittest.TestCase):
    def test_new_changed_kept_aged_and_notes(self):
        first = T.merge([], [line(), line(line_no="2", line_status="Active")], today=TODAY)
        self.assertEqual((first["added"], first["changed"], first["aged_out"]), (2, 0, 0))
        rows = [list(r) for r in first["rows"]]
        rows[0][T._COL["Notes"]] = "called 10/28"            # Carlos types a note on the first row
        rows[0][T._COL["Being worked on"]] = "Yes"
        rows[0][T._COL["Delivered Message Sent"]] = "Yes"      # rc_contact_sync.delivered marked it
        noted_key = T._key(rows[0])
        # next morning: line 1 activates, line 2 missing from the feed (kept), an old line
        # arrives (kept too: nothing ages off since 2026-11-15)
        later = TODAY + dt.timedelta(days=1)
        old = line(order_date="08/01/2026", wireless_order="WOOLD", line_no="1")
        second = T.merge(rows, [line(line_status="Active"), old], today=later)
        self.assertEqual(second["aged_out"], 0)
        self.assertEqual((second["added"], second["changed"]), (1, 1))
        by_key = {T._key(r): r for r in second["rows"]}
        self.assertEqual(len(by_key), 3)                      # line 2 kept though absent today
        self.assertEqual(by_key[("wo", "woold", "1")][T._COL["Order Date"]], "08/01/2026")
        self.assertEqual(by_key[noted_key][T._COL["Notes"]], "called 10/28")
        self.assertEqual(by_key[noted_key][T._COL["Being worked on"]], "Yes")
        self.assertEqual(by_key[noted_key][T._COL["Delivered Message Sent"]], "Yes")
        l1 = by_key[("wo", "wo555", "1")]
        self.assertEqual(l1[T._COL["Line Status"]], "Active")
        self.assertEqual(l1[T._COL["Last Updated"]], "10/30/2026")
        l2 = by_key[("wo", "wo555", "2")]
        self.assertEqual(l2[T._COL["Last Updated"]], "10/29/2026")   # untouched -> stamp kept

    def test_unchanged_line_keeps_its_stamp(self):
        first = T.merge([], [line()], today=TODAY)
        second = T.merge(first["rows"], [line()], today=TODAY + dt.timedelta(days=3))
        self.assertEqual(second["changed"], 0)
        self.assertEqual(second["rows"][0][T._COL["Last Updated"]], "10/29/2026")

    def test_nothing_ages_out(self):
        # Carlos 2026-11-15: "we shouldn't be removing anything past 60 days"
        self.assertIsNone(T.DAYS_KEPT)
        stale = T.line_row(line(order_date="08/01/2026", wireless_order="WOOLD"), "08/02/2026")
        res = T.merge([stale], [line()], today=TODAY)
        self.assertEqual(res["aged_out"], 0)
        self.assertEqual(len(res["rows"]), 2)
        self.assertEqual(res["rows"][-1][T._COL["Order Date"]], "08/01/2026")   # oldest last

    def test_existing_rows_without_a_line_number_are_dropped(self):
        bad = T.line_row(line(line_no="", customer="Luis Martinez"), "10/29/2026")
        res = T.merge([bad], [line()], today=TODAY)
        self.assertEqual(len(res["rows"]), 1)
        self.assertEqual(res["rows"][0][T._COL["Line"]], "1")

    def test_protected(self):
        self.assertNotIn(T.TAB, T.PROTECTED_TABS)




class LineIndexTests(unittest.TestCase):
    """2026-11-11: the order-log workbook's tab columns are looked up by the
    line's phone number; a miss falls back to a one-line order's DSI #."""

    def test_by_phone_digits_then_single_line_dsi(self):
        a = T.line_row(line(device="945-392-8474", dsi="DSI123", line_no="1"), "10/29/2026")
        b = T.line_row(line(device="945-392-8475", dsi="DSI123", line_no="2"), "10/29/2026")
        c = T.line_row(line(device="214-555-0100", dsi="DSI777", line_no="1", customer="ANA R"),
                       "10/28/2026")
        ix = T.LineIndex([a, b, c])
        self.assertEqual(len(ix), 3)
        self.assertEqual(ix.value("Line", phone="9453928475"), "2")              # digits match
        self.assertEqual(ix.value("Line", phone="(945) 392-8474"), "1")
        self.assertEqual(ix.value("Line", phone="19453928474"), "1")             # leading 1 dropped
        self.assertEqual(ix.value("Last Updated", phone="9453928474"), "10/29/2026")
        self.assertEqual(ix.value("Customer", phone="0000000001", dsi="DSI777"), "Ana R")  # one-line order
        self.assertEqual(ix.value("Line", phone="0000000002", dsi="DSI123"), "")     # two lines: no guess
        self.assertEqual(ix.value("Line", phone="", dsi=""), "")
        self.assertEqual(len(ix.hits), 3)
        self.assertEqual(len(ix.misses), 2)

    def test_preview_merges_todays_feed_over_the_live_tab(self):
        from unittest import mock
        prior = [list(T.HEADERS), T.line_row(line(), "10/20/2026")]
        prior[1][T._COL["Notes"]] = "called 10/21"

        class _WS:
            def get_all_values(self):
                return prior

        class _SH:
            def worksheet(self, _title):
                return _WS()

        quiet = lambda *_a, **_k: None  # noqa: E731
        with mock.patch.object(T, "today_lines", lambda today=None, log=print: [line()]), \
             mock.patch.object(T.ZipIndex, "from_export", lambda today, log=print: None), \
             mock.patch("automations.recruiting_report.fill.open_by_key", lambda *_a, **_k: _SH()):
            rows = T.preview(TODAY, log=quiet)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][T._COL["Last Updated"]], "10/20/2026")   # unchanged line keeps its stamp
        self.assertEqual(rows[0][T._COL["Notes"]], "called 10/21")

    def test_preview_without_the_live_tab_blanks_last_updated(self):
        from unittest import mock
        quiet = lambda *_a, **_k: None  # noqa: E731
        with mock.patch.object(T, "today_lines", lambda today=None, log=print: [line()]), \
             mock.patch.object(T.ZipIndex, "from_export", lambda today, log=print: None), \
             mock.patch("automations.recruiting_report.fill.open_by_key",
                        side_effect=RuntimeError("no sheet")):
            rows = T.preview(TODAY, log=quiet)
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][T._COL["Last Updated"]], "")
        self.assertEqual(rows[0][T._COL["Customer"]], "John Doe")

    def test_preview_is_none_without_a_feed(self):
        from unittest import mock
        with mock.patch.object(T, "today_lines", lambda today=None, log=print: None):
            self.assertIsNone(T.preview(TODAY, log=lambda *_a, **_k: None))


class EmailColumnTests(unittest.TestCase):
    """11/11: the e-mail off the SaraPlus customer card (customer_email.py's
    cache) rides the tab like Zip does -- filled on today's lines, looked up
    on carried rows still blank, kept when neither can place it."""

    def test_email_index_fills_fresh_and_carried_rows(self):
        idx = T.EmailIndex({"DSI123": "jerry@example.com"})
        self.assertEqual(idx.for_line(line()), "jerry@example.com")
        self.assertEqual(idx.lookup("dsi123"), "jerry@example.com")
        first = T.merge([], [line()], today=TODAY, email_of=idx.for_line)
        self.assertEqual(first["rows"][0][T._COL["Email"]], "jerry@example.com")
        # a carried row (feed forgot it) with a blank Email gets it by DSI
        prior = [list(r) for r in first["rows"]]
        prior[0][T._COL["Email"]] = ""
        second = T.merge(prior, [], today=TODAY, email_lookup=idx.lookup)
        self.assertEqual(second["rows"][0][T._COL["Email"]], "jerry@example.com")
        # no index at all: the tab's own value stays
        prior[0][T._COL["Email"]] = "kept@example.com"
        third = T.merge(prior, [line()], today=TODAY)
        self.assertEqual(third["rows"][0][T._COL["Email"]], "kept@example.com")
        # 11/11: a KNOWN order's value replaces the tab's -- blank included --
        # so a wrong address (the rep's) comes off; an unknown order keeps its own
        blank = T.EmailIndex({"DSI123": ""})
        self.assertTrue(blank.known("dsi123")); self.assertFalse(blank.known("DSI9"))
        fourth = T.merge(prior, [line()], today=TODAY, email_of=blank.for_line,
                         email_lookup=blank.lookup, email_known=blank.known)
        self.assertEqual(fourth["rows"][0][T._COL["Email"]], "")
        fifth = T.merge(prior, [], today=TODAY, email_lookup=blank.lookup, email_known=blank.known)
        self.assertEqual(fifth["rows"][0][T._COL["Email"]], "")
        other = T.EmailIndex({"DSI9": "x@example.com"})
        sixth = T.merge(prior, [line()], today=TODAY, email_of=other.for_line,
                        email_lookup=other.lookup, email_known=other.known)
        self.assertEqual(sixth["rows"][0][T._COL["Email"]], "kept@example.com")

    def test_old_tab_without_email_column_remaps(self):
        old_hdr = [h for h in T.HEADERS if h != "Email"]
        old_row = [dict(zip(T.HEADERS, T.line_row(line(), "11/10/2026")))[h] for h in old_hdr]
        out = T.merge([old_row], [], today=TODAY, existing_header=old_hdr)
        self.assertEqual(out["rows"][0][T._COL["Email"]], "")
        self.assertEqual(out["rows"][0][T._COL["Customer"]], old_row[old_hdr.index("Customer")])


class ValidationTests(unittest.TestCase):
    def test_yes_no_rule_cleared_everywhere_before_it_is_set(self):
        # 11/11: the dropdown rule stayed on column R (Last Updated) after the
        # columns shifted -- every data cell there showed a red corner
        reqs = T._format_requests(7, 10, 0)
        dv = [r["setDataValidation"] for r in reqs if "setDataValidation" in r]
        self.assertNotIn("rule", dv[0])                      # the first one clears
        self.assertEqual(dv[0]["range"]["startColumnIndex"], 0)
        self.assertGreaterEqual(dv[0]["range"]["endColumnIndex"], len(T.HEADERS))
        cols = {d["range"]["startColumnIndex"] for d in dv[1:]}
        self.assertEqual(cols, {T._COL["Being worked on"], T._COL["Delivered Message Sent"]})
        # 11/14: Being worked on also offers "Not saveable"; Delivered Message Sent stays Yes / No
        opts = {d["range"]["startColumnIndex"]: [v["userEnteredValue"] for v in d["rule"]["condition"]["values"]]
                for d in dv[1:]}
        self.assertEqual(opts[T._COL["Being worked on"]], ["Yes", "No", "Not saveable"])
        self.assertEqual(opts[T._COL["Delivered Message Sent"]], ["Yes", "No"])


class ActivationDateTests(unittest.TestCase):
    """11/11: the line's activation date comes off the Tableau export (DTR
    Active Date by spe.TN) -- Tableau is what the paycheck follows; the
    SaraPlus feed only says Active with no date."""

    HDR = ["Customer Name", "Customer Zip Simple", "spe.TN", "spe.Account BAN",
           "sp.SPM Number", "DTR Active Date", "DTR Status"]

    def test_index_reads_dtr_active_date_by_phone(self):
        zi = T.ZipIndex.from_rows(self.HDR, [
            ["John Doe", "75060", "9453928474", "BAN9", "DSI123", "11/8/2026", "Posted"],
            ["Jane Roe", "75061", "2145550000", "BAN1", "DSI1", "", "Pending"]])
        self.assertEqual(zi.active_date("945-392-8474"), "11/08/2026")
        self.assertEqual(zi.active_date("214-555-0000"), "")
        self.assertEqual(zi.active_for_line(line()), "11/08/2026")

    def test_fills_fresh_and_carried_rows_and_restamps(self):
        zi = T.ZipIndex.from_rows(self.HDR, [
            ["John Doe", "75060", "9453928474", "BAN9", "DSI123", "11/8/2026", "Posted"]])
        first = T.merge([], [line()], today=TODAY, active_of=zi.active_for_line)
        self.assertEqual(first["rows"][0][T._COL["Activation Date"]], "11/08/2026")
        # a carried row without one gets it by its Phone #
        prior = [list(r) for r in first["rows"]]
        prior[0][T._COL["Activation Date"]] = ""
        second = T.merge(prior, [], today=TODAY, active_lookup=zi.active_date)
        self.assertEqual(second["rows"][0][T._COL["Activation Date"]], "11/08/2026")
        # the date arriving is a state change: Last Updated restamps
        prior[0][T._COL["Last Updated"]] = "10/20/2026"
        third = T.merge(prior, [line()], today=TODAY, active_of=zi.active_for_line)
        self.assertEqual(third["rows"][0][T._COL["Last Updated"]], "10/29/2026")
        self.assertEqual(third["changed"], 1)
        # no export today: what the tab has stays
        prior[0][T._COL["Activation Date"]] = "11/01/2026"
        fourth = T.merge(prior, [line()], today=TODAY)
        self.assertEqual(fourth["rows"][0][T._COL["Activation Date"]], "11/01/2026")

    def test_old_tab_without_the_column_remaps(self):
        old_hdr = [h for h in T.HEADERS if h != "Activation Date"]
        full = dict(zip(T.HEADERS, T.line_row(line(), "11/10/2026")))
        out = T.merge([[full[h] for h in old_hdr]], [], today=TODAY, existing_header=old_hdr)
        self.assertEqual(out["rows"][0][T._COL["Activation Date"]], "")
        self.assertEqual(out["rows"][0][T._COL["Port Status"]], full["Port Status"])


class DateSpellingTests(unittest.TestCase):
    """11/11: Week Ending read back as both 11/08/2026 and 11/8/2026 and sorted
    as two values -- carried rows are re-spelt and the date columns get one
    date format on every rewrite."""

    def test_carried_rows_dates_are_respelt(self):
        prior = T.line_row(line(), "11/9/2026")
        prior[T._COL["Week Ending"]] = "11/8/2026"
        prior[T._COL["Order Date"]] = "10/24/26"
        out = T.merge([prior], [], today=TODAY)
        r = out["rows"][0]
        self.assertEqual(r[T._COL["Week Ending"]], "11/08/2026")
        self.assertEqual(r[T._COL["Order Date"]], "10/24/2026")
        self.assertEqual(r[T._COL["Last Updated"]], "11/09/2026")

    def test_date_columns_get_one_format_after_a_reset(self):
        reqs = [r["repeatCell"] for r in T._format_requests(7, 10, 0) if "repeatCell" in r]
        fmts = [(r["range"]["startColumnIndex"], r["range"]["endColumnIndex"],
                 r["cell"]["userEnteredFormat"].get("numberFormat", {}))
                for r in reqs if "numberFormat" in r["cell"].get("userEnteredFormat", {})]
        self.assertEqual(fmts[0][0], 0)                                  # the reset comes first
        self.assertGreaterEqual(fmts[0][1], len(T.HEADERS))
        dates = {c0 for c0, c1, f in fmts if f.get("type") == "DATE"}
        self.assertEqual(dates, {T._COL[c] for c in T._DATE_COLS})
        texts = {c0 for c0, c1, f in fmts if f.get("type") == "TEXT"}
        self.assertEqual(texts, {T._COL[c] for c in T._TEXT_COLS})





class PayPeriod(unittest.TestCase):
    """2026-11-11 pm: column B. Cancelled / Disconnected by status, else the
    activation week + Friday pay date off the row's Activation Date, else
    Pending."""

    def test_rules(self):
        act = dt.date(2026, 11, 3)                       # Tue -> deposit week Mon 11/2 - Sun 11/8, paid Fri 11/13
        self.assertEqual(T.pay_period_for("Active", act), "11/2-11/8 • Paid 11/13")
        # 11/20: a SUNDAY closes its Mon-Sun week (Subba Rao / Georgeatte, Sun 11/1, paid on CS 11.1)
        self.assertEqual(T.pay_period_for("Active", dt.date(2026, 11, 1)), "10/26-11/1 • Paid 11/6")
        self.assertEqual(T.pay_period_for("Shipped", None), "Pending")
        self.assertEqual(T.pay_period_for("Active", None), "Pending")           # active on the feed, not posted yet
        self.assertEqual(T.pay_period_for("Disconnected", act), "Disconnected")
        self.assertEqual(T.pay_period_for("Cancelled", act), "Cancelled")
        self.assertEqual(T.pay_period_for("Canceled", None), "Cancelled")
        self.assertEqual(T.pay_period_for("Active", None, prior="11/2-11/8 • Paid 11/13"),
                         "11/2-11/8 • Paid 11/13")                              # export lag: keep the week
        self.assertEqual(T.pay_period_for("Active", None, prior="Pending"), "Pending")
        self.assertEqual(T.pay_week_label(dt.date(2026, 12, 30)), "12/28-1/3 • Paid 1/8")

    def test_fresh_carried_and_relabelled_rows(self):
        active_of = lambda l: "11/3/2026"  # noqa: E731 -- Tableau placed the line
        first = T.merge([], [line(line_status="Active")], today=TODAY, active_of=active_of)
        row = first["rows"][0]
        self.assertEqual(row[T._COL["Pay Period"]], "11/2-11/8 • Paid 11/13")
        # next day the export cannot place the line: Activation Date carries, so does the week
        second = T.merge(first["rows"], [line(line_status="Active")], today=TODAY + dt.timedelta(days=1))
        self.assertEqual(second["rows"][0][T._COL["Pay Period"]], "11/2-11/8 • Paid 11/13")
        # the feed drops the line (carried row): still labelled off its own cells
        carried = T.merge(second["rows"], [], today=TODAY + dt.timedelta(days=2))
        self.assertEqual(carried["rows"][0][T._COL["Pay Period"]], "11/2-11/8 • Paid 11/13")
        # cancelled / disconnected win even though the line had a week
        third = T.merge(first["rows"], [line(line_status="Cancelled")], today=TODAY + dt.timedelta(days=1), active_of=active_of)
        self.assertEqual(third["rows"][0][T._COL["Pay Period"]], "Cancelled")
        fourth = T.merge(first["rows"], [line(line_status="Disconnected")], today=TODAY + dt.timedelta(days=1))
        self.assertEqual(fourth["rows"][0][T._COL["Pay Period"]], "Disconnected")
        # a shipped line with no activation date is Pending
        fifth = T.merge([], [line(line_status="Shipped")], today=TODAY, active_of=lambda l: "")
        self.assertEqual(fifth["rows"][0][T._COL["Pay Period"]], "Pending")

    def test_old_tab_without_the_column_gets_it(self):
        old_hdr = [h for h in T.HEADERS if h != "Pay Period"]
        old_row = [c for h, c in zip(T.HEADERS, T.line_row(line(), "10/20/2026", active_of=lambda l: "10/21/2026"))
                   if h != "Pay Period"]
        out = T.merge([old_row], [], today=TODAY, existing_header=old_hdr)
        self.assertEqual(out["rows"][0][T._COL["Pay Period"]], "10/19-10/25 • Paid 10/30")
        self.assertEqual(out["rows"][0][T._COL["Customer"]], "John Doe")


class ShippingNotesTests(unittest.TestCase):
    """11/11 pm: Shipping Notes sits after Ship Date, starts blank on a fresh
    line and is carried by line key through every rewrite (att_order_status
    writes it every morning)."""

    def test_blank_on_fresh_lines_and_carried(self):
        r = T.line_row(line(), "11/11/2026")
        self.assertEqual(len(r), len(T.HEADERS))
        self.assertEqual(r[T._COL["Shipping Notes"]], "")
        self.assertEqual(r[T._COL["Delivered"]], "")
        self.assertEqual(r[T._COL["Ship Date"]], "10/25/2026")
        self.assertEqual(r[T._COL["Churn Bucket"]], "")                 # still last
        prior = list(r); prior[T._COL["Shipping Notes"]] = "11/11 AT&T: on the way; FedEx 879: returning"
        out = T.merge([prior], [line()], today=TODAY)
        self.assertEqual(out["rows"][0][T._COL["Shipping Notes"]], "11/11 AT&T: on the way; FedEx 879: returning")
        self.assertIn("Shipping Notes", T.CARRIED)
        self.assertIn("Shipping Status", T.CARRIED)
        self.assertEqual(r[T._COL["Shipping Status"]], "")





class ChurnBucketTests(unittest.TestCase):
    """2026-11-11 pm: Churn Bucket, the last column, off the row's Activation
    Date -- the cancelled workbook's rule, now ageing on the tab."""

    def test_last_column_and_fresh_rows(self):
        self.assertEqual(T.HEADERS[-2], "Churn Bucket")                 # Port Status sits after it since 11/18
        self.assertEqual(T.HEADERS[_COLX("Delivered Message Sent") + 3], "Churn Bucket")   # Shipping Status + Notes sit between (11/12)
        r = T.line_row(line(line_status="Active"), "11/09/2026", active_of=lambda l: "11/3/2026")
        self.assertEqual(r[T._COL["Churn Bucket"]], "0-30 Day")
        self.assertEqual(len(r), len(T.HEADERS))
        self.assertEqual(T.line_row(line(), "x")[T._COL["Churn Bucket"]], "")        # no activation / odd stamp

    def test_ages_on_every_rewrite_and_blank_until_activated(self):
        act = lambda l: "11/3/2026"  # noqa: E731
        day0 = dt.date(2026, 11, 9)
        first = T.merge([], [line(line_status="Active")], today=day0, active_of=act)
        self.assertEqual(first["rows"][0][T._COL["Churn Bucket"]], "0-30 Day")
        later = T.merge(first["rows"], [], today=dt.date(2026, 12, 10))             # 37 days: carried row ages
        self.assertEqual(later["rows"][0][T._COL["Churn Bucket"]], "30 Day")
        # 61 days after activation (order still inside the 60-day keep window)
        much_later = T.merge([], [line(order_date="11/4/2026", line_status="Disconnected")],
                             today=dt.date(2027, 1, 3), active_of=act)
        self.assertEqual(much_later["rows"][0][T._COL["Churn Bucket"]], "60 Day")     # a disconnect keeps its cohort
        pending = T.merge([], [line(line_status="Shipped")], today=day0, active_of=lambda l: "")
        self.assertEqual(pending["rows"][0][T._COL["Churn Bucket"]], "")


def _COLX(name):
    return T._COL[name]


class HoverNoteTests(unittest.TestCase):
    def test_shipping_notes_hover_notes_wiped_on_rewrite(self):
        # 11/11 pm: the hover notes belong to a line; rows move on every
        # rewrite, so the column's notes are cleared and the 06:50 job re-adds them
        reqs = [r["repeatCell"] for r in T._format_requests(7, 10, 0) if "repeatCell" in r]
        wipes = [r for r in reqs if r.get("fields") == "note"]
        self.assertEqual(len(wipes), 1)
        # 11/17: every column, so a column move leaves no note behind on the wrong column
        self.assertEqual(wipes[0]["range"]["startColumnIndex"], 0)
        self.assertGreater(wipes[0]["range"]["endColumnIndex"], T._COL["Shipping Notes"])
        self.assertEqual(wipes[0]["cell"], {"note": ""})


class NotSaveableColour(unittest.TestCase):
    """11/14: "Not saveable" turns the row purple, above yellow and below
    green / red, and every rewrite puts the rule back."""

    def test_rule_order_green_red_purple_yellow(self):
        rules = T.status_rules()
        self.assertEqual(len(rules), 4)
        W = chr(65 + T._COL["Being worked on"])
        self.assertIn('="active"', rules[0][0])
        self.assertIn('"disconnected"', rules[1][0])
        self.assertEqual(rules[2], (f'=LOWER(TRIM(${W}2))="not saveable"', T.PURPLE))
        self.assertIn('<>"active"', rules[3][0])                       # yellow is last
        self.assertIn(T.NOT_SAVEABLE, T.DROPDOWNS["Being worked on"])

    def test_rewrite_adds_all_four_rules_in_order(self):
        reqs = T._format_requests(7, 10, 3)
        self.assertEqual(sum(1 for r in reqs if "deleteConditionalFormatRule" in r), 3)
        adds = [r["addConditionalFormatRule"] for r in reqs if "addConditionalFormatRule" in r]
        self.assertEqual([a["index"] for a in adds], [0, 1, 2, 3])
        c = adds[2]["rule"]["booleanRule"]["format"]["backgroundColor"]
        self.assertEqual((c["red"], c["green"], c["blue"]), T.PURPLE)





class NotSaveableMarks(unittest.TestCase):
    """2026-11-15: the tab's Not saveable marks for the activation-by-week board."""

    def test_marks_off_a_tab_read(self):
        a = T.line_row(line(dsi="DSI7", line_no="1"), "10/29/2026")
        a[T._COL["Being worked on"]] = "Not saveable"
        b = T.line_row(line(dsi="DSI7", line_no="2", device="(817) 296-5740"), "10/29/2026")
        b[T._COL["Being worked on"]] = " not SAVEABLE "
        c = T.line_row(line(dsi="DSI8", line_no="1"), "10/29/2026")
        c[T._COL["Being worked on"]] = "Yes"
        m = T.marks_from_rows(list(T.HEADERS), [a, b, c])
        self.assertEqual(m["n"], 2)
        self.assertEqual(m["dsi_line"], {("dsi7", "1"), ("dsi7", "2")})
        self.assertEqual(m["phone"], {"9453928474", "8172965740"})
        # an older tab layout (the column somewhere else) resolves by header
        hdr = ["Being worked on", "DSI #", "Line", "Phone #"]
        m2 = T.marks_from_rows(hdr, [["Not saveable", "DSI9", "4", "214-555-0100"], ["", "DSI9", "5", ""]])
        self.assertEqual((m2["n"], m2["dsi_line"], m2["phone"]), (1, {("dsi9", "4")}, {"2145550100"}))
        self.assertEqual(T.marks_from_rows(list(T.HEADERS), [])["n"], 0)


class Nov17Columns(unittest.TestCase):
    """11/17: a folded column group under Customer, Taylor's Notes beside
    Notes, and a Disconnect Date off the Tableau export."""

    def test_group_is_added_folded_with_its_toggle_above_customer(self):
        start, end = T.group_span()
        self.assertEqual((start, end), (T._COL["Email"], T._COL["Plan"] + 1))
        self.assertEqual(start, T._COL["Device"] + 1)             # Device is the last column in view
        self.assertEqual(T._COL["Device"], T._COL["Customer"] + 1)
        reqs = T.group_requests(7, [])
        self.assertFalse(reqs[0]["updateSheetProperties"]["properties"]["gridProperties"]["columnGroupControlAfter"])
        add = [r["addDimensionGroup"]["range"] for r in reqs if "addDimensionGroup" in r]
        self.assertIn((start, end, "COLUMNS"), [(a["startIndex"], a["endIndex"], a["dimension"]) for a in add])
        upd = [r["updateDimensionGroup"] for r in reqs if "updateDimensionGroup" in r]
        self.assertTrue(all(u["dimensionGroup"]["collapsed"] for u in upd))

    def test_an_existing_group_on_the_same_span_is_left_as_carlos_has_it(self):
        start, end = T.group_span()
        same = [{"range": {"startIndex": a, "endIndex": b}, "depth": 1} for a, b in T.group_spans()]  # open: no 'collapsed'
        reqs = T.group_requests(7, same)
        self.assertEqual([list(r)[0] for r in reqs], ["updateSheetProperties"])
        stale = [{"range": {"startIndex": start, "endIndex": end}, "depth": 1}]       # yesterday: only the customer fold
        kinds = [list(r)[0] for r in T.group_requests(7, stale)]
        self.assertEqual(kinds, ["updateSheetProperties", "deleteDimensionGroup"]
                         + ["addDimensionGroup", "updateDimensionGroup"] * 2)
        # the full rewrite carries them
        self.assertIn("addDimensionGroup", [list(r)[0] for r in T._format_requests(7, 10, 0)])

    def test_taylors_notes_is_carried_like_notes(self):
        self.assertIn("Taylor's Notes", T.CARRIED)
        prior = T.line_row(line(), "11/16/2026")
        prior[T._COL["Taylor's Notes"]] = "called 11/16, voicemail"
        prior[T._COL["Notes"]] = "carlos note"
        out = T.merge([prior], [line()], today=TODAY)
        self.assertEqual(out["rows"][0][T._COL["Taylor's Notes"]], "called 11/16, voicemail")
        self.assertEqual(out["rows"][0][T._COL["Notes"]], "carlos note")

    def test_old_layout_remaps_into_the_new_one_by_name(self):
        old_hdr = ["Week Ending", "Pay Period", "Rep", "Customer", "Zip", "Email", "Order Date", "DSI #",
                   "Wireless Order #", "BAN", "Line", "Type", "Phone #", "Device", "Plan", "Line Status",
                   "Ship Date", "Delivered", "Activation Date", "Port Status", "Last Updated", "Notes",
                   "Being worked on", "Delivered Message Sent", "Shipping Status", "Shipping Notes", "Churn Bucket"]
        full = dict(zip(T.HEADERS, T.line_row(line(), "11/16/2026")))
        full.update({"Notes": "n1", "Being worked on": "Not saveable", "Shipping Notes": "11/16: x", "Zip": "75060",
                     "Email": "a@b.com"})
        out = T.merge([[full[h] for h in old_hdr]], [], today=TODAY, existing_header=old_hdr)
        r = dict(zip(T.HEADERS, out["rows"][0]))
        self.assertEqual((r["Notes"], r["Being worked on"], r["Shipping Notes"], r["Zip"], r["Email"]),
                         ("n1", "Not saveable", "11/16: x", "75060", "a@b.com"))
        self.assertEqual((r["Phone #"], r["DSI #"], r["Taylor's Notes"], r["Disconnect Date"]),
                         ("945-392-8474", "DSI123", "", ""))

    def test_disconnect_date_off_the_export(self):
        hdr = ["Customer Name", "Customer Zip Simple", "spe.TN", "spe.Account BAN", "sp.SPM Number",
               "DTR Active Date", "DTR Status", "Status Date"]
        zi = T.ZipIndex.from_rows(hdr, [
            ["John Doe", "75060", "9453928474", "BAN9", "DSI123", "11/1/2026", "Disconnected", "11/12/2026"],
            ["Jane Roe", "75061", "2145550000", "BAN1", "DSI1", "11/2/2026", "Posted", "11/2/2026"]])
        self.assertEqual(zi.disconnect_date("945-392-8474"), "11/12/2026")
        self.assertEqual(zi.disconnect_date("214-555-0000"), "")           # Posted: its status date is no disconnect
        self.assertEqual(zi.disconnect_for_line(line()), "11/12/2026")
        first = T.merge([], [line()], today=TODAY, disc_of=zi.disconnect_for_line)
        self.assertEqual(first["rows"][0][T._COL["Disconnect Date"]], "11/12/2026")
        prior = [list(x) for x in first["rows"]]
        prior[0][T._COL["Disconnect Date"]] = ""
        second = T.merge(prior, [], today=TODAY, disc_lookup=zi.disconnect_date)
        self.assertEqual(second["rows"][0][T._COL["Disconnect Date"]], "11/12/2026")
        third = T.merge(first["rows"], [line()], today=TODAY)              # no export today: kept
        self.assertEqual(third["rows"][0][T._COL["Disconnect Date"]], "11/12/2026")
        self.assertIn("Disconnect Date", T._DATE_COLS)


class NobodyUsesLetters(unittest.TestCase):
    def test_no_reader_addresses_the_tab_by_letter(self):
        # 11/17 pm: Carlos moved seven columns in two days and asked that "whatever
        # fills all this out" keep up. It does only because every reader and
        # writer resolves by header name; this pins that for the modules that
        # touch the tab.
        import pathlib, re
        root = pathlib.Path(__file__).resolve().parents[1]
        files = ["nds_metrics/att_order_status.py", "nds_metrics/customer_email.py",
                 "rc_contact_sync/delivered.py", "rc_contact_sync/followup.py"]
        bad = re.compile(r"""['"]NDS Order Log['"]!\$?[A-Z]{1,2}\$?\d|T\.HEADERS\[\d+\]|order_log_tab\.HEADERS\[\d+\]""")
        for f in files:
            src = (root / f).read_text(encoding="utf-8")
            self.assertIsNone(bad.search(src), f)


if __name__ == "__main__":
    unittest.main()


class StrayLines(unittest.TestCase):
    """11/19: the feed read filed another order's lines under Danzell Vaughn
    (a 1-line order) and the tab kept them for good -- 'Porting Issue' on a
    customer whose phone was delivered. A row for a line its order does not
    have goes; everything the feed has merely forgotten stays."""

    def _tab(self, *lines):
        return T.merge([], list(lines), today=TODAY)["rows"]

    def test_line_the_order_does_not_have_is_removed(self):
        vaughn = dict(customer="DANZELL VAUGHN", wireless_order="99-1", dsi="DSI1")
        # the bad day: four lines filed under Vaughn's order
        bad = self._tab(*[line(line_no=str(n), line_count="4", line_status="Porting Issue", **vaughn)
                          for n in (1, 2, 3, 4)])
        self.assertEqual(len(bad), 4)
        # today the feed has the order whole: it says 1 line and shows 1
        out = T.merge(bad, [line(line_no="1", line_count="1", line_status="Delivered", **vaughn)],
                      today=TODAY + dt.timedelta(days=1))
        self.assertEqual([(r[T._COL["Line"]], r[T._COL["Line Status"]]) for r in out["rows"]],
                         [("1", "Delivered")])
        self.assertEqual(len(out["strays_removed"]), 3)
        self.assertIn("L3", out["strays_removed"][1])

    def test_order_the_feed_forgot_is_kept(self):
        old = self._tab(line(line_no="1", line_count="1", customer="OLD ORDER", wireless_order="99-8", dsi="DSI8"))
        out = T.merge(old, [line(line_no="1", line_count="1", wireless_order="99-1", dsi="DSI1")],
                      today=TODAY + dt.timedelta(days=1))
        self.assertEqual(len(out["rows"]), 2)
        self.assertEqual(out["strays_removed"], [])

    def test_nothing_is_removed_when_the_feed_is_not_whole_for_the_order(self):
        o = dict(customer="X", wireless_order="99-1", dsi="DSI1")
        tab = self._tab(line(line_no="1", line_count="2", **o), line(line_no="2", line_count="2", **o))
        # the order says 2 lines but only one row came through: leave line 2 alone
        out = T.merge(tab, [line(line_no="1", line_count="2", **o)], today=TODAY + dt.timedelta(days=1))
        self.assertEqual(len(out["rows"]), 2)
        self.assertEqual(out["strays_removed"], [])

    def test_stray_with_a_typed_note_is_held_and_reported(self):
        o = dict(customer="X", wireless_order="99-1", dsi="DSI1")
        tab = self._tab(line(line_no="1", line_count="2", **o), line(line_no="2", line_count="2", **o))
        tab[1][T._COL["Notes"]] = "called 11/18"
        out = T.merge(tab, [line(line_no="1", line_count="1", **o)], today=TODAY + dt.timedelta(days=1))
        self.assertEqual(len(out["rows"]), 2)
        self.assertEqual(out["strays_removed"], [])
        self.assertEqual(len(out["strays_held"]), 1)


class Nov27DateFold(unittest.TestCase):
    """11/27, Carlos: "lets move column D, R, S, T, & T to be grouped in column
    c. So there should be + above column D that opens all those up"."""

    def test_the_five_dates_fold_right_after_order_date(self):
        self.assertEqual(T.HEADERS[:3], ("Week Ending", "Pay Period", "Order Date"))
        self.assertEqual(T.HEADERS[3:8], ("Last Updated", "Ship Date", "Delivered", "Activation Date",
                                          "Disconnect Date"))
        self.assertEqual(T.group_spans(), [(3, 8), T.group_span()])
        reqs = T.group_requests(7, [])
        add = [(r["addDimensionGroup"]["range"]["startIndex"], r["addDimensionGroup"]["range"]["endIndex"])
               for r in reqs if "addDimensionGroup" in r]
        self.assertEqual(add, T.group_spans())

    def test_customer_fold_still_right_after_device(self):
        start, _ = T.group_span()
        self.assertEqual(start, T._COL["Device"] + 1)
