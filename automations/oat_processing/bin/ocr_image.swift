// OCR one image file with macOS's own Vision framework and print the text.
//
// WHY: plenty of resumes are IMAGES (a designed CV exported as a picture, or a
// scan). They render perfectly for a human — Carlos read Michelle Valencia's
// number straight off the screen — but carry no text layer, so every text-based
// read returns empty and the applicant looks uncontactable. Vision ships with
// macOS, so this needs no install on any machine that runs the push.
//
// Usage:  swift ocr_image.swift <path>      (prints recognized text to stdout)
import Foundation
import Vision
import AppKit

guard CommandLine.arguments.count > 1,
      let img = NSImage(contentsOfFile: CommandLine.arguments[1]),
      let cg = img.cgImage(forProposedRect: nil, context: nil, hints: nil) else {
    FileHandle.standardError.write("cannot open image\n".data(using: .utf8)!)
    exit(2)
}
let req = VNRecognizeTextRequest()
req.recognitionLevel = .accurate
req.usesLanguageCorrection = false          // phone digits, not prose
let handler = VNImageRequestHandler(cgImage: cg, options: [:])
do {
    try handler.perform([req])
    for obs in (req.results ?? []) {
        if let top = obs.topCandidates(1).first { print(top.string) }
    }
} catch {
    FileHandle.standardError.write("ocr failed: \(error)\n".data(using: .utf8)!)
    exit(3)
}
