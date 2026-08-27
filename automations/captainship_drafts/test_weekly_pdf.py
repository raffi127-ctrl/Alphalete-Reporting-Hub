"""Offline tests for the weekly-dispositions PDF attachment (Rafael 2026-08-27).

No ownerville, no network, no Sheet: everything here runs off a temp render_dir
with a couple of tiny PNGs in it.

    python -m unittest automations.captainship_drafts.test_weekly_pdf
"""
from __future__ import annotations

import datetime as dt
import json
import tempfile
import unittest
from pathlib import Path

from automations.captainship_drafts import weekly_pdf as W


def _png(path: Path, size=(40, 20)) -> Path:
    from PIL import Image
    path.parent.mkdir(parents=True, exist_ok=True)
    Image.new("RGB", size, (200, 180, 160)).save(path)
    return path


class TheWeekItAttaches(unittest.TestCase):
    """El ancla NO es week_window: de martes a sábado esa devuelve la semana EN
    CURSO, y el adjunto tiene que ser la del último reporte del domingo."""

    def test_every_weekday_points_at_the_last_sunday_report(self):
        # Semana Mon 8/17 - Sat 8/22, reportada el domingo 8/23.
        for d in range(23, 30):                     # Sun 8/23 … Sat 8/29
            today = dt.date(2026, 8, d)
            want = (dt.date(2026, 8, 29) if d >= 30
                    else dt.date(2026, 8, 22))
            self.assertEqual(W.last_report_saturday(today), want,
                             f"{today} ({today:%a})")

    def test_sunday_moves_to_the_week_that_just_ended(self):
        """El domingo 06:15 los PNGs nuevos ya están escritos, así que ese
        mismo día el adjunto pasa a la semana recién cerrada."""
        self.assertEqual(W.last_report_saturday(dt.date(2026, 8, 30)),
                         dt.date(2026, 8, 29))
        self.assertEqual(W.last_report_saturday(dt.date(2026, 8, 31)),
                         dt.date(2026, 8, 29))

    def test_the_span_in_the_name_says_which_week(self):
        self.assertEqual(
            W.attachment_name("Rafael Hidalgo", dt.date(2026, 8, 22)),
            "Weekly Knock Dispositions - Rafael Hidalgo - Aug 17-22, 2026.pdf")
        # semana a caballo de dos meses
        self.assertIn("Aug 31 - Sep 5",
                      W.attachment_name("X", dt.date(2026, 9, 5)))


class ThePagesItPrints(unittest.TestCase):

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.sat = dt.date(2026, 8, 22)
        self.addCleanup(self._tmp.cleanup)

    def _capture(self, labels, *, sat=None, day="2026-08-22"):
        sat = sat or self.sat
        wroot = self.root / "knock_dispo_rafael"
        items = []
        for lab in labels:
            if lab == "Captainship Summary":
                p = _png(wroot / "summary"
                         / f"knock_dispo_summary_{sat.isoformat()}.png")
            else:
                slug = "".join(c if c.isalnum() else "_" for c in lab.lower())
                p = _png(wroot / slug
                         / f"weekly_knock_dispositions_{sat.isoformat()}.png")
            items.append([lab, str(p)])
        man = (self.root
               / f"knocks_manifest_rafael_{day}_{sat.isoformat()}.json")
        man.write_text(json.dumps({
            "kinds": ["daily_knocks", "knock_dispo"],
            "items": {"knock_dispo": items, "daily_knocks": []},
            "errors": {}}), encoding="utf-8")
        return man

    def test_the_manifest_gives_order_and_real_display_names(self):
        self._capture(["Captainship Summary", "Chan Park", "Sahil Multani"])
        pages = W.pages_for(self.root, "rafael", self.sat)
        self.assertEqual([lab for lab, _p in pages],
                         ["Captainship Summary", "Chan Park", "Sahil Multani"])

    def test_a_png_the_manifest_names_but_disk_lost_is_dropped(self):
        """Media sección es peor que una lenta — pero acá, a diferencia del
        build, la respuesta correcta es imprimir lo que SÍ está."""
        self._capture(["Captainship Summary", "Chan Park"])
        gone = (self.root / "knock_dispo_rafael" / "chan_park"
                / f"weekly_knock_dispositions_{self.sat.isoformat()}.png")
        gone.unlink()
        pages = W.pages_for(self.root, "rafael", self.sat)
        self.assertEqual([lab for lab, _p in pages], ["Captainship Summary"])

    def test_without_a_manifest_it_still_finds_the_boards(self):
        self._capture(["Captainship Summary", "Chan Park"])
        for man in self.root.glob("knocks_manifest_*.json"):
            man.unlink()
        pages = W.pages_for(self.root, "rafael", self.sat)
        self.assertEqual([lab for lab, _p in pages],
                         ["Captainship Summary", "Chan Park"])

    def test_a_missed_sunday_falls_back_to_the_week_before(self):
        older = dt.date(2026, 8, 15)
        self._capture(["Captainship Summary"], sat=older, day="2026-08-15")
        sat, pages = W.find_week(self.root, "rafael", dt.date(2026, 8, 27))
        self.assertEqual(sat, older)             # NO 8/22: esa no se corrió
        self.assertEqual(len(pages), 1)

    def test_nothing_on_disk_means_no_attachment_not_a_crash(self):
        class Cap:
            key, display_name = "rafael", "Rafael Hidalgo"
        self.assertIsNone(W.build(Cap(), dt.date(2026, 8, 27), self.root,
                                  out_dir=self.root / "kept",
                                  logfn=lambda *_a: None))

    def test_it_writes_one_page_per_board(self):
        from automations.shared.pkg import ensure
        PdfReader = ensure("pypdf").PdfReader

        class Cap:
            key, display_name = "rafael", "Rafael Hidalgo"
        self._capture(["Captainship Summary", "Chan Park", "Sahil Multani"])
        got = W.build(Cap(), dt.date(2026, 8, 27), self.root,
                      out_dir=self.root / "kept", logfn=lambda *_a: None)
        self.assertIsNotNone(got)
        pdf, name = got
        self.assertEqual(len(PdfReader(str(pdf)).pages), 3)
        self.assertEqual(
            name,
            "Weekly Knock Dispositions - Rafael Hidalgo - Aug 17-22, 2026.pdf")


class ItSurvivesTheTempSweep(unittest.TestCase):
    """RENDER_DIR es el temp del SO. Los PNGs del domingo pueden desaparecer el
    miércoles; el adjunto NO puede desaparecer con ellos."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.out = self.root / "kept"
        self.addCleanup(self._tmp.cleanup)

    class Cap:
        key, display_name = "rafael", "Rafael Hidalgo"

    def _sunday_capture(self, sat=dt.date(2026, 8, 22)):
        wroot = self.root / "knock_dispo_rafael"
        p = _png(wroot / "summary"
                 / f"knock_dispo_summary_{sat.isoformat()}.png")
        man = self.root / f"knocks_manifest_rafael_{sat.isoformat()}_{sat.isoformat()}.json"
        man.write_text(json.dumps({
            "kinds": ["knock_dispo"],
            "items": {"knock_dispo": [["Captainship Summary", str(p)]]},
            "errors": {}}), encoding="utf-8")
        return p

    def test_the_pdf_is_reused_after_the_pngs_are_swept(self):
        png = self._sunday_capture()
        first = W.build(self.Cap(), dt.date(2026, 8, 24), self.root,
                        out_dir=self.out, logfn=lambda *_a: None)
        self.assertIsNotNone(first)
        # miércoles: el SO barrió el temp
        png.unlink()
        for man in self.root.glob("knocks_manifest_*.json"):
            man.unlink()
        later = W.build(self.Cap(), dt.date(2026, 8, 26), self.root,
                        out_dir=self.out, logfn=lambda *_a: None)
        self.assertIsNotNone(later)
        self.assertEqual(later[0], first[0])       # el MISMO archivo
        self.assertEqual(later[1], first[1])       # y la misma semana en el nombre

    def test_fresh_pngs_win_over_the_kept_pdf(self):
        """Un re-pull del lunes tiene que PISAR el PDF del domingo, no quedar
        detrás de él."""
        self._sunday_capture()
        got = W.build(self.Cap(), dt.date(2026, 8, 24), self.root,
                      out_dir=self.out, logfn=lambda *_a: None)
        before = got[0].stat().st_mtime_ns
        # el lunes redibuja el board con DOS páginas
        wroot = self.root / "knock_dispo_rafael"
        _png(wroot / "chan_park" / "weekly_knock_dispositions_2026-08-22.png")
        for man in self.root.glob("knocks_manifest_*.json"):
            man.unlink()                            # cae al glob de disco
        again = W.build(self.Cap(), dt.date(2026, 8, 24), self.root,
                        out_dir=self.out, logfn=lambda *_a: None)
        from automations.shared.pkg import ensure
        self.assertNotEqual(again[0].stat().st_mtime_ns, before)
        self.assertEqual(len(ensure("pypdf").PdfReader(str(again[0])).pages), 2)


class TheHookInRunPy(unittest.TestCase):
    """El bundle decide con `captain.sections`, que es una PROPERTY. Llamarla
    como método pasó los tests y tumbó la corrida real con "'list' object is
    not callable" — esto lo fija."""

    def test_sections_is_a_property_and_rafael_declares_the_weekly(self):
        from automations.captainship_drafts import config
        cap = next(c for c in config.CAPTAINS if c.key == "rafael")
        self.assertIsInstance(cap.sections, list)
        self.assertIn("knock_dispo", {k for _h, k in cap.sections})

    def test_only_the_flavors_with_weekly_boards_get_an_attachment(self):
        """B2B y NDS no tienen board semanal: no les puede colgar un adjunto."""
        from automations.captainship_drafts import config
        with_weekly = {c.flavor for c in config.CAPTAINS
                       if "knock_dispo" in {k for _h, k in c.sections}}
        self.assertEqual(with_weekly, {"rafael", "fiber"})


class TheMimeItProduces(unittest.TestCase):
    """El adjunto va en el multipart/mixed de AFUERA; las imágenes inline
    tienen que quedar intactas adentro de su multipart/related — que es lo que
    se rompió el 2026-07-27 al ponerle nombre a una parte de adentro."""

    def test_the_pdf_rides_outside_the_related_container(self):
        from email.message import EmailMessage
        msg = EmailMessage()
        msg.set_content("text")
        msg.add_alternative("<div>html</div>", subtype="html")
        html_part = msg.get_payload()[1]
        html_part.add_related(b"\x89PNG", maintype="image", subtype="png",
                              cid="<01-x@a>")
        with tempfile.TemporaryDirectory() as td:
            pdf = Path(td) / "w.pdf"
            pdf.write_bytes(b"%PDF-1.4\n")
            msg.add_attachment(pdf.read_bytes(), maintype="application",
                               subtype="pdf", filename="Weekly.pdf")
        self.assertEqual(msg.get_content_type(), "multipart/mixed")
        names = [p.get_filename() for p in msg.iter_attachments()]
        self.assertIn("Weekly.pdf", names)
        # la imagen inline sigue SIN nombre y adentro del related
        related = [p for p in msg.walk()
                   if p.get_content_type() == "multipart/related"]
        self.assertEqual(len(related), 1)
        inline = [p for p in related[0].walk()
                  if p.get_content_type() == "image/png"]
        self.assertEqual(len(inline), 1)
        self.assertIsNone(inline[0].get_filename())


if __name__ == "__main__":
    unittest.main()
