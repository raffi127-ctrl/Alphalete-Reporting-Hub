// Text out of a resume FILE with nothing but macOS: PDFKit for a PDF's text
// layer, Vision for pictures (an image file, or the pages of a PDF that is a
// scan / a designed template exported as a picture).
//
// Usage:  osascript -l JavaScript read_file.js text <file.pdf>
//         osascript -l JavaScript read_file.js ocr  <file.pdf|png|jpg>
ObjC.import('Foundation');
ObjC.import('AppKit');
ObjC.import('Quartz');
ObjC.import('Vision');

function ocrURL(url) {
  var req = $.VNRecognizeTextRequest.alloc.init;
  req.recognitionLevel = 0;
  req.usesLanguageCorrection = false;
  var h = $.VNImageRequestHandler.alloc.initWithURLOptions(url, $({}));
  if (!h.performRequestsError($([req]), Ref())) return [];
  var out = [], res = req.results;
  for (var i = 0; i < res.count; i++) {
    var c = res.objectAtIndex(i).topCandidates(1);
    if (c.count > 0) out.push(c.objectAtIndex(0).string.js);
  }
  return out;
}

// Rendered pages go through a temp TIFF: passing nil arguments for a CGImage
// from JXA arrives as NSNull and throws.
function ocrImage(img) {
  var tmp = $.NSTemporaryDirectory().js + "lucy_page_" + Date.now() + ".tiff";
  img.TIFFRepresentation.writeToFileAtomically(tmp, true);
  var out = ocrURL($.NSURL.fileURLWithPath(tmp));
  $.NSFileManager.defaultManager.removeItemAtPathError(tmp, Ref());
  return out;
}

function run(argv) {
  var mode = argv[0], path = argv[1];
  var url = $.NSURL.fileURLWithPath(path);
  var isPdf = /\.pdf$/i.test(path);
  if (mode === "text") {
    if (!isPdf) return "";
    var doc = $.PDFDocument.alloc.initWithURL(url);
    if (!doc || doc.isNil()) return "";
    var s = doc.string;
    return (s && !s.isNil()) ? s.js : "";
  }
  var lines = [];
  if (isPdf) {
    var d = $.PDFDocument.alloc.initWithURL(url);
    if (!d || d.isNil()) return "";
    var n = Math.min(d.pageCount, 3);       // the number lives on page 1
    for (var p = 0; p < n; p++) {
      var pg = d.pageAtIndex(p);
      var img = pg.thumbnailOfSizeForBox($.NSMakeSize(1700, 2200), 1);
      lines = lines.concat(ocrImage(img));
    }
  } else {
    lines = ocrURL(url);
  }
  return lines.join("\n");
}
