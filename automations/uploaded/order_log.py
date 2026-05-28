"""
Order Log Report — single-file standalone version.

WHAT THIS DOES
  Logs into ownerville → navigates to the ATT Tracker 2.1 - D2D workbook
  in Tableau → opens the ORDER LOG tab → filters Owner Name to a single
  owner and Date Range to "last 1 month → today" → downloads the
  Crosstab CSV → cleans, sorts, color-codes the data → saves a polished
  .xlsx to your Downloads folder ready to drop in Slack.

HOW TO USE
  1. Fill in OWNERVILLE_USERNAME and OWNERVILLE_PASSWORD below.
  2. Install deps (one-time):
         pip install patchright pandas openpyxl python-dateutil
         patchright install chromium
  3. Run:
         python -m automations.order_log_report.run
     (or from inside the folder: `python run.py`)
  4. The .xlsx lands in ~/Downloads/.
"""

# ====================================================================
#  CONFIG — EDIT THIS SECTION
# ====================================================================

# Your ownerville.com login is read from a gitignored local file
# (automations.shared.creds -> ownerville-creds.json at the repo root), NOT
# hardcoded here — the repo was public, so the password must never live in
# source. See _validate_credentials().

# Tableau coordinates.
WORKBOOK_NAME = "ATT Tracker 2.1 - D2D"
TAB_NAME = "ORDER LOG"
OWNER_NAME = "Rafael Hidalgo"

# ====================================================================
#  Implementation — no changes needed below this line for normal use.
# ====================================================================

import asyncio
import re
import tempfile
from contextlib import asynccontextmanager
from datetime import date, datetime
from pathlib import Path
from typing import AsyncIterator, Optional

import pandas as pd
from dateutil.relativedelta import relativedelta
from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter
from patchright.async_api import (
    Page,
    TimeoutError as PlaywrightTimeoutError,
    async_playwright,
)


# === Date range — last 1 month → today (calendar-month aware) =======
END_DATE = date.today()
START_DATE = END_DATE - relativedelta(months=1)


# === Output location =================================================
# Downloads folder works for any user on macOS or Windows.
OUTPUT_DIR = Path.home() / "Downloads"

# Per-run screenshot folder (optional debugging aid). Set to None to disable.
SCREENSHOT_DIR = Path(__file__).resolve().parent / "screenshots"

# Persistent Chrome profile so Cloudflare / ownerville remember us
# between runs. Lives next to this script.
PROFILE_DIR = Path(__file__).resolve().parent / ".browser_profile"


# ====================================================================
#  Browser launcher (patchright + persistent profile)
# ====================================================================

@asynccontextmanager
async def launch_stealth_browser(headless: bool = False) -> AsyncIterator[Page]:
    """
    Yield an anti-detection Playwright Page backed by patchright.

    Patchright is a Playwright fork with stealth patches baked in —
    Cloudflare and similar bot detectors have a much harder time
    spotting it as automated. Using a persistent profile folder
    makes us look like a returning human, not a fresh bot session.
    """
    PROFILE_DIR.mkdir(exist_ok=True)
    async with async_playwright() as p:
        # Prefer the system Chrome binary - patchright's stealth patches
        # are tuned to it and Cloudflare-style detectors leave it alone
        # more often. If Chrome isn't installed on the machine (common
        # on a clean Windows install or in CI), fall back to patchright's
        # bundled Chromium so the run doesn't die at launch.
        try:
            context = await p.chromium.launch_persistent_context(
                user_data_dir=str(PROFILE_DIR),
                channel="chrome",
                headless=headless,
                no_viewport=True,
            )
        except Exception as e:
            print(f"[order_log] system Chrome unavailable ({e!r}) — "
                  "falling back to bundled Chromium", flush=True)
            context = await p.chromium.launch_persistent_context(
                user_data_dir=str(PROFILE_DIR),
                headless=headless,
                no_viewport=True,
            )
        page = context.pages[0] if context.pages else await context.new_page()
        try:
            yield page
        finally:
            await context.close()


# ====================================================================
#  Ownerville login
# ====================================================================

LOGIN_URL = "https://ownerville.com"
CLOUDFLARE_WAIT_SECONDS = 10
PRE_SUBMIT_PAUSE_SECONDS = 3

USERNAME_SELECTOR = (
    'input[type="email"], input[name="username"], input[name="email"], '
    'input[type="text"]'
)
PASSWORD_SELECTOR = 'input[type="password"]'
LOGIN_BUTTON_NAME = re.compile(r"log\s*in|sign\s*in", re.IGNORECASE)
NEXT_BUTTON_NAME = re.compile(r"^\s*next\s*$", re.IGNORECASE)
FINAL_SUBMIT_NAME = re.compile(
    r"sign\s*in|log\s*in|submit|continue|enter", re.IGNORECASE
)


def _validate_credentials() -> tuple[str, str]:
    """Read the ownerville login from the gitignored creds file (not source).
    creds.ownerville_*() raise a clear 'create ownerville-creds.json' error if
    the file/env var is missing."""
    from automations.shared import creds
    return creds.ownerville_username().strip(), creds.ownerville_password().strip()


async def _open_login_form(page: Page) -> None:
    """Click 'Log in' / 'Sign in' on the homepage if visible; otherwise no-op."""
    for role in ("link", "button"):
        candidate = page.get_by_role(role, name=LOGIN_BUTTON_NAME).first
        try:
            if await candidate.is_visible(timeout=2000):
                await candidate.click()
                return
        except PlaywrightTimeoutError:
            continue


async def login(page: Page) -> None:
    """Sign into Ownerville. Returns when the post-login page is loaded."""
    username, password = _validate_credentials()

    print(f"-> Navigating to {LOGIN_URL}")
    await page.goto(LOGIN_URL, wait_until="domcontentloaded")
    await _open_login_form(page)

    print("-> Filling username")
    await page.wait_for_selector(USERNAME_SELECTOR, timeout=15_000)
    await page.fill(USERNAME_SELECTOR, username)

    print("-> Clicking NEXT")
    await page.get_by_role("button", name=NEXT_BUTTON_NAME).first.click()

    await page.wait_for_selector(PASSWORD_SELECTOR, timeout=60_000)

    print(f"-> Letting Cloudflare run for {CLOUDFLARE_WAIT_SECONDS}s "
          "(don't touch the browser)...")
    await asyncio.sleep(CLOUDFLARE_WAIT_SECONDS)

    print("-> Filling password")
    await page.fill(PASSWORD_SELECTOR, password)

    print(f"-> Pausing {PRE_SUBMIT_PAUSE_SECONDS}s before final submit...")
    await asyncio.sleep(PRE_SUBMIT_PAUSE_SECONDS)

    print("-> Clicking final submit button")
    await page.get_by_role("button", name=FINAL_SUBMIT_NAME).first.click()

    print("-> Waiting for post-login page to render...")
    await page.wait_for_load_state("load")
    await page.get_by_text(re.compile(r"^\s*logout\s*$", re.IGNORECASE)).first.wait_for(
        state="visible", timeout=30_000
    )
    print("-> Login complete")


# ====================================================================
#  Tableau navigation
# ====================================================================

SIDEBAR_TABLEAU_PARENT_SELECTOR = 'a.waves-effect:has(i.fa-t)'
SIDEBAR_TABLEAU_SUB_ITEM_NAME = "Tableau"
LOGIN_TO_TABLEAU_TEXT = "Login to Tableau"
TABLEAU_SEARCH_SELECTOR = "#search-omnibox"
TABLEAU_VIZ_SELECTOR = (
    "div.tab-vizContainer, div.tabCanvas, iframe[src*='tableau']"
)

WORKBOOK_FOLDER_SLUGS = {
    "ATT Tracker 2.1 - D2D": "d2d_tracker",
}


def _slugify(text: str) -> str:
    text = re.sub(r'[^a-zA-Z0-9]+', '_', text.lower())
    return text.strip('_')


def _get_csv_save_path(workbook_name: str, tab_name: str, data_dir: Path) -> Path:
    folder_slug = WORKBOOK_FOLDER_SLUGS.get(
        workbook_name, _slugify(workbook_name)
    )
    folder = data_dir / folder_slug
    folder.mkdir(parents=True, exist_ok=True)
    tab_slug = _slugify(tab_name)
    today = date.today().isoformat()
    path = folder / f"{tab_slug}_{today}.csv"
    if path.exists():
        timestamp = datetime.now().strftime("%H%M%S")
        path = folder / f"{tab_slug}_{today}_{timestamp}.csv"
    return path


async def _shot(page: Page, screenshot_dir: Optional[Path], filename: str) -> None:
    if screenshot_dir is None:
        return
    screenshot_dir.mkdir(exist_ok=True)
    await page.screenshot(path=str(screenshot_dir / filename), full_page=True)


async def _resolve_toolbar_scope(page: Page):
    """
    Return the scope (page or iframe) holding the Tableau viz-viewer
    toolbar. Modern Tableau Cloud puts the toolbar inside an iframe.
    """
    iframes = page.locator("iframe")
    count = await iframes.count()
    for i in range(count):
        src = (await iframes.nth(i).get_attribute("src")) or ""
        if any(m in src.lower() for m in ("tableau", "/views/", "/embed/")):
            frame = page.frame_locator("iframe").nth(i)
            try:
                await frame.locator(
                    '[data-tb-test-id="viz-viewer-toolbar-button-download"], #download'
                ).first.wait_for(state="attached", timeout=2000)
                return frame
            except Exception:
                continue
    return page


async def _dismiss_tableau_announcement_modals(page: Page) -> None:
    """
    Dismiss any Tableau Cloud "Upgrade Coming Soon"-style modal that's
    blocking the page. Ticks "Do not show this notification again" so
    it stays gone across runs. No-op if no modal is on screen.
    """
    close_button = page.locator(
        '[data-tb-test-id="postlogin-footer-close-Button"]'
    ).first
    try:
        await close_button.wait_for(state="visible", timeout=2500)
    except Exception:
        try:
            await page.get_by_text(
                "Tableau Cloud Upgrade", exact=False
            ).first.wait_for(state="visible", timeout=1500)
        except Exception:
            return

    print("-> Dismissing Tableau postlogin announcement modal")

    suppress_strategies = [
        page.locator(
            '[data-tb-test-id*="do-not-show" i], '
            '[data-tb-test-id*="dont-show" i], '
            '[data-tb-test-id*="suppress" i]'
        ),
        page.get_by_label("Do not show this notification again"),
        page.get_by_text(
            "Do not show this notification again", exact=False
        ),
    ]
    for locator in suppress_strategies:
        try:
            target = locator.first
            await target.wait_for(state="visible", timeout=1500)
            try:
                if await target.is_checked():
                    break
            except Exception:
                pass
            await target.click()
            break
        except Exception:
            continue

    try:
        await close_button.click()
    except Exception:
        try:
            await page.get_by_role("button", name="Close").first.click()
        except Exception as exc:
            print(f"   (Close click failed: {exc})")

    await page.wait_for_timeout(600)


async def navigate_to_workbook(
    page: Page,
    workbook_name: str,
    tab_name: Optional[str] = None,
    screenshot_dir: Optional[Path] = None,
) -> Page:
    """
    From the post-login Ownerville page, navigate into Tableau and
    open the specified workbook + dashboard tab. Returns the Page
    where the viz renders (Tableau opens in a new browser tab).
    """
    print('-> Clicking sidebar Tableau parent')
    await page.locator(SIDEBAR_TABLEAU_PARENT_SELECTOR).first.click()
    await page.wait_for_timeout(800)

    print('-> Clicking sidebar Tableau sub-item')
    sub_links = page.get_by_role(
        "link", name=SIDEBAR_TABLEAU_SUB_ITEM_NAME, exact=True
    )
    count = await sub_links.count()
    clicked = False
    for i in range(count):
        candidate = sub_links.nth(i)
        if await candidate.is_visible():
            await candidate.click()
            clicked = True
            break
    if not clicked:
        raise RuntimeError("No visible 'Tableau' sub-link found.")

    await page.wait_for_load_state("domcontentloaded")
    await _shot(page, screenshot_dir, "01_sidebar_tableau_clicked.png")
    await _shot(page, screenshot_dir, "02_ownerville_tableau_page.png")

    print(f'-> Clicking "{LOGIN_TO_TABLEAU_TEXT}" — expecting a new tab')
    async with page.context.expect_page() as new_page_info:
        await page.get_by_role(
            "link", name=LOGIN_TO_TABLEAU_TEXT, exact=True
        ).first.click()
    tableau_page = await new_page_info.value
    await tableau_page.wait_for_load_state("domcontentloaded")
    print(f"-> New tab opened at {tableau_page.url}")
    await _shot(tableau_page, screenshot_dir, "03_tableau_landed.png")

    await _dismiss_tableau_announcement_modals(tableau_page)

    print(f'-> Searching Tableau for "{workbook_name}"')
    search_box = tableau_page.locator(TABLEAU_SEARCH_SELECTOR)
    await search_box.wait_for(state="visible", timeout=30_000)
    await search_box.fill(workbook_name)
    await search_box.press("Enter")
    await tableau_page.get_by_text(workbook_name, exact=False).first.wait_for(
        state="visible", timeout=30_000
    )
    await _shot(tableau_page, screenshot_dir, "04_search_results.png")

    await _dismiss_tableau_announcement_modals(tableau_page)

    print(f'-> Clicking workbook tile "{workbook_name}"')
    tile_strategies = [
        tableau_page.locator(
            f'a[data-tb-test-id="Thumbnail"][aria-label="{workbook_name}"]'
        ),
        tableau_page.locator(
            f'[data-tb-test-id="WorkbookCardName"]:has-text("{workbook_name}")'
        ),
        tableau_page.get_by_text(workbook_name, exact=False),
    ]
    tile_clicked = False
    for locator in tile_strategies:
        try:
            await locator.first.wait_for(state="visible", timeout=5000)
            await locator.first.click()
            tile_clicked = True
            break
        except Exception:
            continue
    if not tile_clicked:
        raise RuntimeError(
            f"Couldn't click the workbook tile for '{workbook_name}'."
        )

    print("-> Waiting for the workbook page to settle...")
    await tableau_page.wait_for_timeout(2500)
    if not tab_name:
        try:
            await tableau_page.wait_for_selector(
                TABLEAU_VIZ_SELECTOR, timeout=15_000
            )
        except Exception:
            pass

    await _shot(tableau_page, screenshot_dir, "05_workbook_loaded.png")

    if tab_name:
        print(f'-> Clicking tab/view "{tab_name}"')
        view_strategies = [
            tableau_page.locator(f'a[title="{tab_name}"]'),
            tableau_page.locator(
                f'[data-tb-test-id="name-cell"] a[title="{tab_name}"]'
            ),
            tableau_page.get_by_role("link",   name=tab_name, exact=False),
            tableau_page.get_by_role("option", name=tab_name, exact=False),
            tableau_page.locator("a").filter(has_text=tab_name),
            tableau_page.get_by_text(tab_name, exact=False),
        ]
        clicked = False
        for locator in view_strategies:
            try:
                await locator.first.wait_for(state="visible", timeout=10_000)
                await locator.first.click()
                clicked = True
                break
            except Exception:
                continue
        if not clicked:
            raise RuntimeError(
                f"Couldn't find a visible view tile for '{tab_name}'."
            )

        print("-> Waiting for the viz to render after tab click...")
        await tableau_page.wait_for_timeout(2000)
        try:
            await tableau_page.wait_for_selector(
                TABLEAU_VIZ_SELECTOR, timeout=45_000
            )
        except Exception:
            pass
        await _shot(tableau_page, screenshot_dir, "06_tab_loaded.png")

    print("-> Navigation complete")
    return tableau_page


# ====================================================================
#  Filter automation (Owner Name + Date Range)
# ====================================================================

def _fmt_date(d: date) -> str:
    """Tableau's date textareas accept M/D/YYYY with no leading zeros."""
    return f"{d.month}/{d.day}/{d.year}"


async def _viz_scope(page: Page):
    """
    Return the scope (page or iframe) holding the Tableau viz DOM.
    Filter widgets live wherever the viz lives.
    """
    iframes = page.locator("iframe")
    count = await iframes.count()
    print(f"   (probing {count} iframe(s) for the viz)")
    for i in range(count):
        src = (await iframes.nth(i).get_attribute("src")) or ""
        name = (await iframes.nth(i).get_attribute("name")) or ""
        if any(
            m in (src + name).lower()
            for m in ("tableau", "/views/", "/embed/", "viz")
        ):
            print(f"   (viz lives inside iframe #{i})")
            return page.frame_locator("iframe").nth(i)
    return page


async def _wait_for_viz_ready(viz, page: Page, timeout_ms: int = 60_000) -> None:
    """
    Block until no Tableau loading overlay is visible. `.tab-glass` is
    permanent (transparent click-capture), so we only wait for the
    real loading masks (`.wcGlassPane`, `#loadingGlassPane`).
    """
    glass = ".wcGlassPane:visible, #loadingGlassPane:visible"
    interval_ms, elapsed = 300, 0
    while elapsed < timeout_ms:
        try:
            count = await viz.locator(glass).count()
        except Exception:
            count = 0
        if count == 0:
            return
        await page.wait_for_timeout(interval_ms)
        elapsed += interval_ms
    print(f"   (warning: glass panes still visible after {timeout_ms}ms — proceeding)")


async def _toggle_filter_row(page: Page, row, label: str, want_checked: bool) -> None:
    """
    Toggle a Tableau categorical-filter row to a desired state.

    The outer `.FIItem` div carries `role="checkbox"` and `aria-checked`,
    but Tableau's Dojo widget wires its real click handler to inner
    elements. We try a few targets and verify after each click.
    """
    current = await row.get_attribute("aria-checked")
    wanted = "true" if want_checked else "false"
    if current == wanted:
        print(f'   "{label}" already {wanted} — no toggle needed')
        return

    print(f'   toggling "{label}": aria-checked {current} → {wanted}')
    targets = [
        ("FIText anchor",   "a.FIText"),
        ("fakeCheckBox",    "div.fakeCheckBox"),
        ("FICheckRadio",    "input.FICheckRadio"),
        ("facetOverflow",   "div.facetOverflow"),
        ("row itself",      None),
    ]
    for label_text, sub_selector in targets:
        target = row.locator(sub_selector).first if sub_selector else row
        try:
            await target.click(force=True, timeout=2000)
        except Exception:
            continue
        await page.wait_for_timeout(350)
        new_state = await row.get_attribute("aria-checked")
        if new_state == wanted:
            print(f"     after {label_text}: aria-checked={new_state}")
            return

    raise RuntimeError(
        f'Could not toggle "{label}" to aria-checked={wanted}.'
    )


async def set_owner_name_filter(page: Page, owner_name: str) -> None:
    """Restrict the Owner Name filter to a single owner."""
    print(f'-> Setting Owner Name filter to "{owner_name}"')
    viz = await _viz_scope(page)

    owner_filter = viz.locator(
        '.CategoricalFilter:has(h3.FilterTitle[title="Owner Name"])'
    )
    combobox = owner_filter.locator('[role="combobox"]').first
    await combobox.wait_for(state="visible", timeout=15_000)
    await combobox.click()
    await page.wait_for_timeout(800)

    all_item = viz.locator(".FIItem.all-item").first
    await all_item.wait_for(state="visible", timeout=5000)
    await _toggle_filter_row(page, all_item, "(All)", want_checked=False)

    owner_row = viz.locator(
        f'.FIItem:has(a.FIText[title="{owner_name}"])'
    ).first
    await owner_row.wait_for(state="visible", timeout=5000)
    await owner_row.scroll_into_view_if_needed()
    await _toggle_filter_row(page, owner_row, owner_name, want_checked=True)

    print("   clicking Apply")
    enabled_apply = viz.locator(
        'button[title="Apply"]:not([disabled])'
    ).first
    await enabled_apply.wait_for(state="visible", timeout=10_000)
    await enabled_apply.click()

    print("   waiting for viz to finish reloading")
    await _wait_for_viz_ready(viz, page)
    await page.wait_for_timeout(1500)


async def set_date_range(page: Page, start_date: date, end_date: date) -> None:
    """Set the Start Date and End Date textareas at the top of the view."""
    print(
        f"-> Setting date range: {_fmt_date(start_date)} → {_fmt_date(end_date)}"
    )
    viz = await _viz_scope(page)

    for label, d in [("Start Date", start_date), ("End Date", end_date)]:
        await _wait_for_viz_ready(viz, page)
        box = viz.locator(f'textarea[aria-label="{label}"]').first
        await box.wait_for(state="visible", timeout=10_000)
        # force=True bypasses Tableau's permanent transparent click-capture.
        await box.click(force=True)
        await box.fill(_fmt_date(d))
        await box.press("Enter")

    await _wait_for_viz_ready(viz, page)


# ====================================================================
#  Download (Crosstab → CSV)
# ====================================================================

async def download_dashboard_csv(
    page: Page,
    workbook_name: str,
    tab_name: str,
    data_dir: Path,
) -> Path:
    """Trigger Download → Crosstab (CSV) and save to `data_dir`."""
    csv_path = _get_csv_save_path(workbook_name, tab_name, data_dir)
    scope = await _resolve_toolbar_scope(page)

    print('-> Opening Tableau Download menu')
    download_button = scope.locator(
        '[data-tb-test-id="viz-viewer-toolbar-button-download"], #download'
    ).first
    await download_button.wait_for(state="visible", timeout=15_000)
    await download_button.click()

    print('-> Clicking Crosstab option')
    crosstab_item = scope.locator(
        '[data-tb-test-id="download-flyout-TextMenuItem"]:has-text("Crosstab")'
    ).first
    await crosstab_item.wait_for(state="visible", timeout=10_000)
    await crosstab_item.click()
    await page.wait_for_timeout(1000)

    print('-> Selecting CSV format')
    # Click the label, not the input — label intercepts clicks.
    csv_label = scope.locator(
        '[data-tb-test-id="crosstab-options-dialog-radio-csv-Label"]'
    ).first
    await csv_label.wait_for(state="visible", timeout=10_000)
    await csv_label.click()

    print(f'-> Triggering download → {csv_path}')
    dialog_download = scope.locator(
        '[data-tb-test-id="export-crosstab-export-Button"]'
    ).first
    async with page.expect_download() as download_info:
        await dialog_download.click()

    download = await download_info.value
    await download.save_as(str(csv_path))
    print(f"-> Saved {csv_path}")
    return csv_path


# ====================================================================
#  CSV → cleaned + color-coded .xlsx
# ====================================================================
#
# Translated 1:1 from the original Google Apps Script generateCleanedLog().
# Filter columns, drop empty-Rep rows, sort by Rep → Status order → Order
# Date, then write a formatted .xlsx with status-driven row colors.
# ====================================================================

COLUMNS_TO_KEEP = [
    "Rep",
    "sp.Order Date (copy)",
    "Customer Name",
    "sp.SPM Number",
    "Product Type (Broken Out)",
    "Package",
    "spe.Status",
    "spe.Install Date",
    "Activatoin Date (order log)",  # typo matches source data
]

FRIENDLY_HEADERS = [
    "Rep",
    "Order Date",
    "Customer Name",
    "SPM Number",
    "Product Type",
    "Package",
    "Status",
    "Install Date",
    "Activation Date",
]

STATUS_ORDER = [
    "Active",
    "Cancelled",
    "Delivered",
    "Disconnected",
    "Open",
    "Pending Shipment",
    "Scheduled",
    "Shipped",
    "",
]

STATUS_COLORS = {
    "Active":           "57BB8A",
    "Cancelled":        "E67C73",
    "Disconnected":     "E67C73",
    "Scheduled":        "FFD666",
    "Open":             "FFD666",
    "Pending Shipment": "FFD666",
    "Shipped":          "FFD666",
    "Delivered":        "F6B26B",
}

STATUS_TEXT_COLORS = {
    "Cancelled":    "CC0000",
    "Disconnected": "CC0000",
    "Delivered":    "B45F06",
}

DATE_COLUMN_INDEXES = (2, 8, 9)


def _status_sort_key(value) -> int:
    cleaned = str(value or "").strip()
    return STATUS_ORDER.index(cleaned) if cleaned in STATUS_ORDER else 999


def _load_and_clean(csv_path: Path) -> pd.DataFrame:
    # Tableau exports UTF-16 LE with tab separators despite the .csv name.
    df = pd.read_csv(csv_path, encoding="utf-16", sep="\t")

    rep_blank = df["Rep"].isna() | (df["Rep"].astype(str).str.strip() == "")
    df = df.loc[~rep_blank].copy()

    df = df[COLUMNS_TO_KEEP].copy()

    for src_col in ("sp.Order Date (copy)", "spe.Install Date",
                    "Activatoin Date (order log)"):
        df[src_col] = pd.to_datetime(df[src_col], errors="coerce")

    df["_status_order"] = df["spe.Status"].map(_status_sort_key)
    df = df.sort_values(
        by=["Rep", "_status_order", "sp.Order Date (copy)"],
        kind="mergesort",
        na_position="last",
    ).drop(columns="_status_order")

    df.columns = FRIENDLY_HEADERS
    return df


def _thin_border() -> Border:
    side = Side(border_style="thin", color="000000")
    return Border(left=side, right=side, top=side, bottom=side)


def _autosize_columns(ws, df: pd.DataFrame) -> None:
    for col_idx, header in enumerate(FRIENDLY_HEADERS, start=1):
        col_series = df[header]
        # Use a defensive str() conversion per-cell. pandas's .astype(str)
        # leaves Arrow-backed nulls as `None`/NaN floats on newer pandas
        # versions, and .map(len) then trips on TypeError: 'float' has no
        # len. A plain generator + str() per value is bulletproof.
        max_len = max(
            (len(header),)
            + tuple(len(str(v)) for v in col_series if v is not None
                    and not (isinstance(v, float) and pd.isna(v)))
        )
        ws.column_dimensions[get_column_letter(col_idx)].width = max_len + 4


def csv_to_xlsx(csv_path: Path, output_dir: Path) -> Path:
    """Build the cleaned, color-coded .xlsx ready for Slack."""
    output_dir.mkdir(parents=True, exist_ok=True)
    df = _load_and_clean(csv_path)

    filename = f"Order Log {date.today():%m-%d-%Y}.xlsx"
    out_path = output_dir / filename

    wb = Workbook()
    ws = wb.active
    ws.title = "Cleaned Order Log"

    border = _thin_border()
    header_fill = PatternFill("solid", fgColor="434343")
    header_font = Font(bold=True, color="FFFFFF")
    center_v = Alignment(vertical="center")

    for col_idx, header in enumerate(FRIENDLY_HEADERS, start=1):
        cell = ws.cell(row=1, column=col_idx, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = center_v
        cell.border = border

    status_col_position = FRIENDLY_HEADERS.index("Status")

    for row_offset, row in enumerate(df.itertuples(index=False), start=2):
        status = str(row[status_col_position] or "").strip()
        bg = STATUS_COLORS.get(status, "FFFFFF")
        fc = STATUS_TEXT_COLORS.get(status, "000000")
        fill = PatternFill("solid", fgColor=bg)
        font = Font(color=fc)

        for col_idx, value in enumerate(row, start=1):
            if pd.isna(value):
                value = None
            elif col_idx in DATE_COLUMN_INDEXES and hasattr(value, "to_pydatetime"):
                value = value.to_pydatetime()

            cell = ws.cell(row=row_offset, column=col_idx, value=value)
            cell.fill = fill
            cell.font = font
            cell.alignment = center_v
            cell.border = border
            if col_idx in DATE_COLUMN_INDEXES:
                cell.number_format = "m/d/yyyy"

    _autosize_columns(ws, df)
    ws.freeze_panes = "A2"

    wb.save(out_path)
    return out_path


# ====================================================================
#  Entry point
# ====================================================================

async def main(owner_name: str = OWNER_NAME, post_to_slack: bool = True) -> None:
    # Intermediate CSV goes to a tempdir that auto-cleans on exit.
    # Final .xlsx is the only artifact left on disk (in Downloads).
    xlsx_path: Optional[Path] = None
    with tempfile.TemporaryDirectory(prefix="order_log_") as tmp:
        tmp_dir = Path(tmp)

        async with launch_stealth_browser() as page:
            await login(page)

            tableau_page = await navigate_to_workbook(
                page,
                workbook_name=WORKBOOK_NAME,
                tab_name=TAB_NAME,
                screenshot_dir=SCREENSHOT_DIR,
            )

            await set_owner_name_filter(tableau_page, owner_name)
            await set_date_range(tableau_page, START_DATE, END_DATE)

            csv_path = await download_dashboard_csv(
                tableau_page,
                workbook_name=WORKBOOK_NAME,
                tab_name=TAB_NAME,
                data_dir=tmp_dir,
            )

            xlsx_path = csv_to_xlsx(csv_path, OUTPUT_DIR)
            print(f"\n✓ Saved to Downloads: {xlsx_path.name}")

    # Slack post happens AFTER the browser context is torn down so a
    # failing Slack call can never strand a logged-in patchright session.
    # Skipped for non-Raf ad-hoc runs so we never noise up the Metrics
    # thread with someone else's order log.
    if xlsx_path is None:
        return
    if not post_to_slack:
        print("  (Skipping Slack post — --no-slack passed.)")
        return
    if owner_name != OWNER_NAME:
        print(f"  (Skipping Slack post — owner is {owner_name!r}, "
              f"Metrics thread is for {OWNER_NAME!r} only.)")
        return

    today = date.today()
    # Match Eve's manual filename pattern: 'Order Log MM-DD-YYYY.xlsx'.
    slack_filename = f"Order Log {today:%m-%d-%Y}.xlsx"
    try:
        from automations.shared.slack_metrics_post import (
            post_reply_with_file, SlackPostError,
        )
        result = post_reply_with_file(
            xlsx_path,
            comment="Order Log",
            react_emoji="clipboard",       # 📋 — matches the Metrics workflow header line
            file_name=slack_filename,
        )
        print(f"  ✓ Slack: posted to today's Metrics thread "
              f"(file={result.get('file')})")
    except SlackPostError as e:
        print(f"  ⚠ Slack post failed: {e}")
        print("    .xlsx is still in Downloads — you can drag it into Slack manually.")


if __name__ == "__main__":
    # `--owner "Carlos Hidalgo"` lets the same script back a separate
    # 'Carlos Order Log' Hub card without duplicating the codebase.
    # Defaults to OWNER_NAME (Rafael Hidalgo) so the existing Raf card
    # keeps working with no args.
    import argparse
    _ap = argparse.ArgumentParser(description="Download a filtered Order Log")
    _ap.add_argument("--owner", default=OWNER_NAME,
                     help=f"Tableau 'Owner Name' filter value (default: {OWNER_NAME!r})")
    _ap.add_argument("--no-slack", action="store_true",
                     help="Skip the Slack post (just save the .xlsx to Downloads).")
    _args = _ap.parse_args()
    asyncio.run(main(_args.owner, post_to_slack=not _args.no_slack))