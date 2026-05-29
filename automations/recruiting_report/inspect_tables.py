"""Capture every table on the currently-attached ApplicantStream page,
plus the full visible text. Use this after CDP attach to map data rows."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from patchright.sync_api import sync_playwright

CDP_URL = "http://localhost:9222"
OUT_PATH = Path(__file__).resolve().parent / "page-tables.json"


def main() -> int:
    with sync_playwright() as p:
        browser = p.chromium.connect_over_cdp(CDP_URL)
        target = None
        for ctx in browser.contexts:
            for page in ctx.pages:
                if "applicantstream" in page.url:
                    target = page
                    break
            if target:
                break
        if not target:
            print("No applicantstream tab open.")
            return 1

        # Extract every <table> as a 2D array of text cells.
        tables = target.evaluate(
            """
            () => {
              const result = [];
              document.querySelectorAll('table').forEach((tbl, i) => {
                const rows = [];
                tbl.querySelectorAll('tr').forEach(tr => {
                  const cells = [];
                  tr.querySelectorAll('th, td').forEach(td => {
                    cells.push((td.innerText || '').trim().replace(/\\s+/g, ' '));
                  });
                  if (cells.length > 0) rows.push(cells);
                });
                if (rows.length > 0) {
                  result.push({
                    table_index: i,
                    row_count: rows.length,
                    rows: rows,
                  });
                }
              });
              return result;
            }
            """
        )

        full_text = target.locator("body").inner_text()

        out = {
            "url": target.url,
            "title": target.title(),
            "tables_count": len(tables),
            "tables": tables,
            "full_text_length": len(full_text),
            "full_text": full_text,
        }
        OUT_PATH.write_text(json.dumps(out, indent=2, default=str))
        print(f"✓ Wrote {len(tables)} tables ({len(full_text)} chars body text) to {OUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
