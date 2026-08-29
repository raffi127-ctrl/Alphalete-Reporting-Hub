"""OCR only fires when the text layer is empty, and it reads an image resume.

Regression for 2026-08-28: image resumes (a designed CV exported as a picture)
render perfectly for a human but carry no text, so every extractor returned ""
and the applicant read as "no phone on resume" — the verdict that removes them.
"""
import os, tempfile
from automations.oat_processing import resume_download as rd


def _pdf(image_only: bool):
    import fitz
    d = fitz.open(); p = d.new_page()
    p.insert_text((72, 120), "MICHELLE VALENCIA", fontsize=26)
    p.insert_text((72, 200), "Phone:", fontsize=13)
    p.insert_text((72, 220), "972-978-1088", fontsize=13)
    tmp = tempfile.mkdtemp(); path = os.path.join(tmp, "r.pdf")
    d.save(path); d.close()
    if not image_only:
        return path
    png = os.path.join(tmp, "p.png")
    with fitz.open(path) as doc:
        doc[0].get_pixmap(dpi=180).save(png)
    d2 = fitz.open(); p2 = d2.new_page(width=612, height=792)
    p2.insert_image(p2.rect, filename=png)
    out = os.path.join(tmp, "img.pdf"); d2.save(out); d2.close()
    return out


def test_text_layer_pdf_needs_no_ocr():
    assert rd.phone_from_file(_pdf(image_only=False)) == "972-978-1088"


def test_image_only_pdf_is_read_by_ocr():
    """The case that used to be reported as a resume with no number."""
    assert rd.phone_from_file(_pdf(image_only=True)) == "972-978-1088"


if __name__ == "__main__":
    for fn in (test_text_layer_pdf_needs_no_ocr, test_image_only_pdf_is_read_by_ocr):
        fn(); print(f"  ok  {fn.__name__}")
    print("2/2 passed")
