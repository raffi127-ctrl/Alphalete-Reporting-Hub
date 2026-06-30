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

let size = NSSize(width: 512, height: 512)
let img = NSImage(size: size)
img.lockFocus()

// Rounded gradient tile (Hub green).
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

img.unlockFocus()

let ok = NSWorkspace.shared.setIcon(img, forFile: path, options: [])
print(ok ? "✅ icon set on \(path)" : "❌ could not set icon on \(path)")
