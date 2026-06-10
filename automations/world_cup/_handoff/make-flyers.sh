#!/bin/bash
# Build both World Cup bracket flyers (Alphalete + Public) in one command.
#
# Usage: bash make-flyers.sh
#
# Requirements: macOS, Python 3, Google Chrome installed at the default path.
# Reads the newest "Round of *.csv" from ~/Downloads and writes both PDFs
# into the same folder as this script.

set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

if [ ! -x "$CHROME" ]; then
  echo "Google Chrome not found at $CHROME"
  echo "Install Chrome or update the CHROME path in this script."
  exit 1
fi

cd "$SCRIPT_DIR"

# Generate HTML for both versions
python3 build_bracket.py            # Alphalete-highlighted, filtered to your groups
python3 build_bracket.py --public   # All groups, no highlighting (shareable)

# Detect which Round was built (from the HTML filename)
ALPHA_HTML=$(ls -t "World Cup 2026 - Round "*" Bracket.html" 2>/dev/null | head -1)
PUBLIC_HTML=$(ls -t "World Cup 2026 - Round "*" Bracket (Public).html" 2>/dev/null | head -1)

if [ -z "$ALPHA_HTML" ] || [ -z "$PUBLIC_HTML" ]; then
  echo "HTML files not found — build_bracket.py may have failed."
  exit 1
fi

# URL-encode spaces in the file:// URLs Chrome wants
url_encode() { python3 -c "import sys, urllib.parse; print('file://' + urllib.parse.quote(sys.argv[1]))" "$1"; }

ALPHA_URL=$(url_encode "$SCRIPT_DIR/$ALPHA_HTML")
PUBLIC_URL=$(url_encode "$SCRIPT_DIR/$PUBLIC_HTML")

ALPHA_PDF="${ALPHA_HTML%.html}.pdf"
PUBLIC_PDF="${PUBLIC_HTML%.html}.pdf"

# Render both to PDF via headless Chrome
"$CHROME" --headless --disable-gpu --no-pdf-header-footer \
  --print-to-pdf="$SCRIPT_DIR/$ALPHA_PDF" "$ALPHA_URL" 2>/dev/null

"$CHROME" --headless --disable-gpu --no-pdf-header-footer \
  --print-to-pdf="$SCRIPT_DIR/$PUBLIC_PDF" "$PUBLIC_URL" 2>/dev/null

echo ""
echo "Done. Two PDFs saved next to this script:"
echo "  Alphalete view (for Rafael): $ALPHA_PDF"
echo "  Public view (to share):      $PUBLIC_PDF"
