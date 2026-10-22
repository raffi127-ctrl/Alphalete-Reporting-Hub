// Read the text off one image with macOS's own Vision framework, through
// osascript's JavaScript bridge. Prints one recognized line per line.
//
// WHY THIS AND NOT ocr_image.swift (2026-10-22): `swift` needs Apple's
// developer tools, and on a Mac without them the shim pops an "install
// developer tools" window on the owner's screen. osascript ships with every
// Mac. An office's own computer (LucyECO) has no Claude key either, so this is
// how it reads a resume Indeed draws as a picture -- Jorge Banos's number sat
// in plain sight on 10/22 and the push called him "no phone".
//
// Usage:  osascript -l JavaScript ocr_screen.js <png path>
ObjC.import('Foundation');
ObjC.import('Vision');
function run(argv) {
  var url = $.NSURL.fileURLWithPath(argv[0]);
  var req = $.VNRecognizeTextRequest.alloc.init;
  req.recognitionLevel = 0;              // accurate
  req.usesLanguageCorrection = false;    // phone digits, not prose
  var handler = $.VNImageRequestHandler.alloc.initWithURLOptions(url, $({}));
  if (!handler.performRequestsError($([req]), Ref())) return "";
  var out = [], res = req.results;
  for (var i = 0; i < res.count; i++) {
    var c = res.objectAtIndex(i).topCandidates(1);
    if (c.count > 0) out.push(c.objectAtIndex(0).string.js);
  }
  return out.join("\n");
}
