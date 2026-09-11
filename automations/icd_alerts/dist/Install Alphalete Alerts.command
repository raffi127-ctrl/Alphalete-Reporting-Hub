#!/bin/bash
# Double-click me. Everything happens in the window that opens.
#
# THIS FILE FINDS A PYTHON AND GETS OUT OF THE WAY. All the real work is in
# setup.py, shared with the Windows installer, so a fix lands on both.
cd "$(dirname "$0")" || exit 1

echo ""
echo "Starting Alphalete Alerts setup..."
echo ""

PY=""
for candidate in python3 /usr/bin/python3 /opt/homebrew/bin/python3 /usr/local/bin/python3; do
  if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 8) else 1)' >/dev/null 2>&1; then
    PY="$candidate"; break
  fi
done

if [ -z "$PY" ]; then
  # /usr/bin/python3 exists on every modern Mac but is a stub until the
  # developer tools are installed; running it pops Apple's own installer.
  echo "This Mac needs Apple's free developer tools first."
  echo "A box will appear now -- click Install, wait for it to finish,"
  echo "then double-click this installer again."
  echo ""
  xcode-select --install 2>/dev/null
  echo "Press return to close."
  read -r _
  exit 1
fi

"$PY" setup.py
STATUS=$?

echo ""
echo "Press return to close this window."
read -r _
exit $STATUS
