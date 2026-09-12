#!/bin/bash
# Double-click me. Everything happens in the window that opens.
#
# THIS FILE FINDS A PYTHON AND GETS OUT OF THE WAY. All the real work is in
# setup.py, shared with the Windows installer, so a fix lands on both.
# The installer sits ABOVE the code, so an owner opening the folder sees two
# things and one of them says Install.
cd "$(dirname "$0")/program files" || {
  echo "This installer is missing its program files folder."
  echo "Please ask the reporting team to send the whole folder again."
  echo ""
  echo "Press return to close."
  read -r _
  exit 1
}

# PAINT THE WINDOW BEFORE ANYTHING ELSE. A .command opens Terminal in whatever
# profile the owner happens to use, and a raw black box in front of somebody
# who was told to ignore it does not look like the thing their reporting team
# sent them.
#
# ALPHALETE'S COLOURS, sampled from the company's own artwork rather than
# guessed: #B93037 is the red in the logo, the shield and both uniform sheets;
# #C1B38F is the gold in the logo. Not the burnt orange on the Total Knocks
# board -- that is the report's table styling, not the brand.
#
# OSC escapes, guarded on stdout being a terminal: piped into a log or run over
# ssh they would be noise, and Terminal is the only thing that reads them.
if [ -t 1 ]; then
  printf '\033]0;Lucy Reports — Setup\007'   # window title
  printf '\033]11;#141110\007'                # background: near-black
  printf '\033]10;#C1B38F\007'                # text: brand gold
  printf '\033]12;#B93037\007'                # cursor: brand red
fi

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
