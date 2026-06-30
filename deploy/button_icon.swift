// Renders a clean app-style icon (green rounded tile + a 🚦 status glyph) and
// sets it on a target file — used to make the "Session Check" desktop button
// pretty instead of the generic Terminal icon.
//
// Usage on the mini:
//   swift deploy/button_icon.swift ~/Desktop/session_check.command
//
// To change the look, edit GLYPH / the two gradient colors below and re-run.
import AppKit

let GLYPH = "🚦"   // try 🔑 / 📡 / ✅ / 🛡️ if you prefer
let target = (CommandLine.arguments.count > 1
              ? CommandLine.arguments[1]
              : "~/Desktop/session_check.command")
let path = (target as NSString).expandingTildeInPath

let px = 512
// Render into an EXPLICIT bitmap rep — an NSImage built via lockFocus only has a
// cached rep, which NSWorkspace.setIcon can't serialize (it returns false).
guard let rep = NSBitmapImageRep(
        bitmapDataPlanes: nil, pixelsWide: px, pixelsHigh: px,
        bitsPerSample: 8, samplesPerPixel: 4, hasAlpha: true, isPlanar: false,
        colorSpaceName: .deviceRGB, bytesPerRow: 0, bitsPerPixel: 0) else {
    print("❌ could not create bitmap"); exit(1)
}
rep.size = NSSize(width: px, height: px)

NSGraphicsContext.saveGraphicsState()
NSGraphicsContext.current = NSGraphicsContext(bitmapImageRep: rep)

let size = NSSize(width: px, height: px)
let tile = NSRect(x: 40, y: 40, width: 432, height: 432)
let rounded = NSBezierPath(roundedRect: tile, xRadius: 104, yRadius: 104)
NSGradient(
    starting: NSColor(calibratedRed: 0.13, green: 0.77, blue: 0.55, alpha: 1.0),
    ending:   NSColor(calibratedRed: 0.03, green: 0.46, blue: 0.39, alpha: 1.0)
)?.draw(in: rounded, angle: -90)

// Soft top highlight, clipped to the tile.
rounded.setClip()
NSColor(white: 1.0, alpha: 0.12).setFill()
NSBezierPath(ovalIn: NSRect(x: -60, y: 250, width: 632, height: 360)).fill()

// Centered glyph.
let glyph = GLYPH as NSString
let attrs: [NSAttributedString.Key: Any] = [.font: NSFont.systemFont(ofSize: 250)]
let gs = glyph.size(withAttributes: attrs)
glyph.draw(at: NSPoint(x: (size.width - gs.width) / 2,
                       y: (size.height - gs.height) / 2 - 14),
           withAttributes: attrs)

NSGraphicsContext.restoreGraphicsState()

let img = NSImage(size: size)
img.addRepresentation(rep)

let ok = NSWorkspace.shared.setIcon(img, forFile: path, options: [])
print(ok ? "✅ icon set on \(path)" : "❌ could not set icon on \(path)")
