// Lucy Screen: the photo page with nothing around it -- no toolbar, tabs, menu
// bar or Dock. Megan 2026-11-25: Lucy 2 "is showing as a webpage and not just a
// fully screen desktop like image".
//
// run.py builds this into a stay-open applet (osacompile) and swaps __PAGE__ for
// the page's path. It only draws a window: no Apple Events, so a Lucy needs no
// permission box for it. Cmd-Q (or Cmd-Tab) gets a person out; the screen job
// brings it back once the Mac has sat idle (run.keep_open).
ObjC.import("Cocoa");
ObjC.import("WebKit");

var PAGE = __PAGE__;
var HIDE_DOCK_AND_MENU_BAR = 2 | 8; // NSApplicationPresentationHideDock | HideMenuBar
var win = null;

function build() {
  var frame = $.NSScreen.mainScreen.frame;
  win = $.NSWindow.alloc.initWithContentRectStyleMaskBackingDefer(frame, 0, 2, false);
  win.setReleasedWhenClosed(false);
  win.setBackgroundColor($.NSColor.colorWithSRGBRedGreenBlueAlpha(0.99, 0.88, 0.92, 1));
  var web = $.WKWebView.alloc.initWithFrameConfiguration(frame, $.WKWebViewConfiguration.alloc.init);
  var url = $.NSURL.fileURLWithPath(PAGE);
  web.loadFileURLAllowingReadAccessToURL(url, url.URLByDeletingLastPathComponent);
  win.setContentView(web);
}

function show() {
  if (win === null) build();
  win.setFrameDisplay($.NSScreen.mainScreen.frame, true);
  var app = $.NSApplication.sharedApplication;
  app.activateIgnoringOtherApps(true);
  app.setPresentationOptions(HIDE_DOCK_AND_MENU_BAR);
  win.makeKeyAndOrderFront(null);
}

function run() { show(); }
function reopen() { show(); }
