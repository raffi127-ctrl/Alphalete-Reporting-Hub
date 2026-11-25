// Lucy Screen: this Lucy's page over the whole monitor -- no toolbar, tabs, menu
// bar or Dock. Megan 2026-11-25: "showing as a webpage and not just a fully
// screen desktop like image", then "we need these screens to run up front all
// the time - the working screens are mostly all I see".
//
// run.py builds this into a stay-open applet (osacompile) and swaps __PAGE__ for
// the page's path. It sends no Apple Events, so a Lucy needs no permission box.
//
// Up front all the time, without getting in the reports' way:
//  - it floats above every window (menu bar and Dock too) but never takes focus;
//  - it tells macOS it is see-through (not opaque), so a Chrome under it is not
//    "covered" -- Chrome slows covered windows down, which stalls captures;
//  - clicks pass through it;
//  - a person touching the mouse or keyboard makes it step aside at once, and
//    it comes back after IDLE_BACK seconds of nobody touching anything.
ObjC.import("Cocoa");
ObjC.import("WebKit");
ObjC.import("CoreGraphics");

var PAGE = __PAGE__;
var LEVEL = 25;        // kCGMainMenuWindowLevel + 1: above the menu bar and Dock
var IDLE_BACK = 300;   // seconds untouched before it comes back (run.IDLE_BEFORE_FRONT)
var win = null;
var shown = false;

function build() {
  var frame = $.NSScreen.mainScreen.frame;
  win = $.NSWindow.alloc.initWithContentRectStyleMaskBackingDefer(frame, 0, 2, false);
  win.setReleasedWhenClosed(false);
  win.setOpaque(false);
  win.setBackgroundColor($.NSColor.colorWithSRGBRedGreenBlueAlpha(0.99, 0.88, 0.92, 0.99));
  win.setLevel(LEVEL);
  win.setIgnoresMouseEvents(true);
  win.setHidesOnDeactivate(false);
  win.setCollectionBehavior(1 | 16 | 256); // all Spaces, stationary, full-screen auxiliary
  var web = $.WKWebView.alloc.initWithFrameConfiguration(frame, $.WKWebViewConfiguration.alloc.init);
  var url = $.NSURL.fileURLWithPath(PAGE);
  web.loadFileURLAllowingReadAccessToURL(url, url.URLByDeletingLastPathComponent);
  win.setContentView(web);
}

function untouched() {
  // any input, real or remote (Screen Sharing), in this login session
  return $.CGEventSourceSecondsSinceLastEventType(0, 4294967295);
}

function place() {
  if (win === null) build();
  var idle = untouched();
  if (shown && idle < 2) {
    win.orderOut(null);
    shown = false;
  } else if (!shown && idle >= IDLE_BACK) {
    win.setFrameDisplay($.NSScreen.mainScreen.frame, true);
    win.orderFrontRegardless;
    shown = true;
  } else if (shown) {
    win.orderFrontRegardless; // stay on top of anything that just opened
  }
}

function show() {
  // launched or re-opened on purpose: show now, whoever is at the machine
  if (win === null) build();
  win.setFrameDisplay($.NSScreen.mainScreen.frame, true);
  win.orderFrontRegardless;
  shown = true;
}

function run() { show(); }
function reopen() { show(); }
function idle() {
  try { place(); } catch (e) {}
  return 1;
}
