import AppKit
import CryptoKit
import Foundation

// Render the repository's SVG directly at every output resolution; no raster upscale.
let app = URL(fileURLWithPath: CommandLine.arguments[1])
let root = app.deletingLastPathComponent().deletingLastPathComponent()
let source = root.appendingPathComponent("assets/superqode-logo.svg")
guard let logo = NSImage(contentsOf: source) else { fatalError("Cannot decode the SuperQode SVG") }
let catalog = app.appendingPathComponent("resources/Assets.xcassets")
let icons = catalog.appendingPathComponent("AppIcon.appiconset")
let marks = catalog.appendingPathComponent("BrandMark.imageset")
let iconset = app.appendingPathComponent("resources/icon.iconset")
let submission = app.appendingPathComponent("app-store/branding")
for directory in [icons, marks, iconset, submission] {
  try FileManager.default.createDirectory(at: directory, withIntermediateDirectories: true)
}

func json(_ object: Any, _ url: URL) throws {
  try JSONSerialization.data(withJSONObject: object, options: [.prettyPrinted, .sortedKeys]).write(
    to: url)
}
func color(_ red: CGFloat, _ green: CGFloat, _ blue: CGFloat, _ alpha: CGFloat = 1) -> NSColor {
  NSColor(srgbRed: red, green: green, blue: blue, alpha: alpha)
}

// The mark stays faithful to the original SVG. All dimensional treatment belongs
// to the macOS tile, with transparent corners and space for its cast shadow.
func drawIcon(_ size: CGFloat) {
  let tile = NSRect(x: size * 0.085, y: size * 0.095, width: size * 0.83, height: size * 0.83)
  let radius = size * 0.184
  let shape = NSBezierPath(roundedRect: tile, xRadius: radius, yRadius: radius)

  NSGraphicsContext.saveGraphicsState()
  let shadow = NSShadow()
  shadow.shadowColor = color(0.025, 0.008, 0.055, 0.48)
  shadow.shadowBlurRadius = size * 0.035
  shadow.shadowOffset = NSSize(width: 0, height: -size * 0.018)
  shadow.set()
  color(0.075, 0.045, 0.12).setFill()
  shape.fill()
  NSGraphicsContext.restoreGraphicsState()

  NSGraphicsContext.saveGraphicsState()
  shape.addClip()
  NSGradient(
    colorsAndLocations: (color(0.055, 0.045, 0.10), 0),
    (color(0.115, 0.07, 0.17), 0.52),
    (color(0.24, 0.18, 0.30), 1))!.draw(in: tile, angle: 90)

  // Light pools below the glass pick up the three brand colours.
  func glow(_ tint: NSColor, at point: NSPoint, radius: CGFloat) {
    NSGradient(starting: tint, ending: tint.withAlphaComponent(0))!.draw(
      fromCenter: point, radius: 0, toCenter: point, radius: radius, options: [])
  }
  glow(
    color(0.49, 0.12, 0.91, 0.40),
    at: NSPoint(x: tile.minX, y: tile.minY), radius: size * 0.70)
  glow(
    color(0.91, 0.10, 0.55, 0.18),
    at: NSPoint(x: tile.maxX, y: tile.midY), radius: size * 0.65)
  glow(
    color(1, 0.64, 0.08, 0.16),
    at: NSPoint(x: tile.maxX, y: tile.maxY), radius: size * 0.50)

  // A broad curved reflection reads as polished glass, without tiny decoration.
  let sheen = NSBezierPath()
  sheen.move(to: NSPoint(x: tile.minX, y: tile.maxY))
  sheen.line(to: NSPoint(x: tile.maxX, y: tile.maxY))
  sheen.line(to: NSPoint(x: tile.maxX, y: size * 0.68))
  sheen.curve(
    to: NSPoint(x: tile.minX, y: size * 0.50),
    controlPoint1: NSPoint(x: size * 0.57, y: size * 0.55),
    controlPoint2: NSPoint(x: size * 0.35, y: size * 0.52))
  sheen.close()
  NSGradient(starting: color(1, 0.94, 1, 0.015), ending: color(1, 0.95, 1, 0.16))!
    .draw(in: sheen, angle: 90)
  NSGraphicsContext.restoreGraphicsState()

  let markRect = NSRect(
    x: size * 0.19, y: size * 0.19,
    width: size * 0.62, height: size * 0.62)
  NSGraphicsContext.saveGraphicsState()
  let emission = NSShadow()
  emission.shadowColor = color(0.91, 0.10, 0.55, size >= 64 ? 0.35 : 0.12)
  emission.shadowBlurRadius = size * 0.016
  emission.shadowOffset = .zero
  emission.set()
  logo.draw(in: markRect, from: .zero, operation: .sourceOver, fraction: 1)
  NSGraphicsContext.restoreGraphicsState()

  // Crisp inset rim: a warm upper edge and a subdued lower edge.
  NSGraphicsContext.saveGraphicsState()
  shape.addClip()
  let rimRect = tile.insetBy(dx: size * 0.0025, dy: size * 0.0025)
  let rim = NSBezierPath(
    roundedRect: rimRect,
    xRadius: radius - size * 0.0025, yRadius: radius - size * 0.0025)
  rim.lineWidth = max(0.5, size * 0.002)
  color(1, 0.90, 1, 0.26).setStroke()
  rim.stroke()
  let inner = NSBezierPath(
    roundedRect: tile.insetBy(dx: size * 0.009, dy: size * 0.009),
    xRadius: radius - size * 0.009, yRadius: radius - size * 0.009)
  inner.lineWidth = max(0.3, size * 0.001)
  color(1, 1, 1, 0.055).setStroke()
  inner.stroke()
  NSGraphicsContext.restoreGraphicsState()
}

func render(_ pixels: Int, background: Bool, opaque: Bool = false, to url: URL) throws {
  let alpha = opaque ? CGImageAlphaInfo.noneSkipLast : CGImageAlphaInfo.premultipliedLast
  guard let colorSpace = CGColorSpace(name: CGColorSpace.sRGB),
    let cgContext = CGContext(
      data: nil, width: pixels, height: pixels, bitsPerComponent: 8, bytesPerRow: 0,
      space: colorSpace, bitmapInfo: alpha.rawValue)
  else { fatalError("Cannot create icon bitmap") }
  let context = NSGraphicsContext(cgContext: cgContext, flipped: false)
  NSGraphicsContext.saveGraphicsState()
  NSGraphicsContext.current = context
  context.imageInterpolation = .high
  let size = CGFloat(pixels)
  if opaque {
    color(0.055, 0.045, 0.08).setFill()
    NSRect(x: 0, y: 0, width: size, height: size).fill()
  }
  if background {
    drawIcon(size)
  } else {
    logo.draw(
      in: NSRect(x: 0, y: 0, width: size, height: size), from: .zero,
      operation: .sourceOver, fraction: 1)
  }
  NSGraphicsContext.restoreGraphicsState()
  guard let cgImage = cgContext.makeImage(),
    let data = NSBitmapImageRep(cgImage: cgImage).representation(using: .png, properties: [:])
  else { fatalError("Cannot encode icon PNG") }
  try data.write(to: url)
}
var images: [[String: String]] = []
var manifest: [[String: Any]] = []
for size in [16, 32, 128, 256, 512] {
  for scale in [1, 2] {
    let filename = "icon_\(size)x\(size)\(scale == 2 ? "@2x" : "").png"
    let target = icons.appendingPathComponent(filename)
    try render(size * scale, background: true, to: target)
    let copy = iconset.appendingPathComponent(filename)
    if FileManager.default.fileExists(atPath: copy.path) {
      try FileManager.default.removeItem(at: copy)
    }
    try FileManager.default.copyItem(at: target, to: copy)
    images.append([
      "idiom": "mac", "size": "\(size)x\(size)", "scale": "\(scale)x", "filename": filename,
    ])
    manifest.append([
      "file": "resources/Assets.xcassets/AppIcon.appiconset/" + filename, "width": size * scale,
      "height": size * scale,
    ])
  }
}
try json(
  ["images": images, "info": ["author": "xcode", "version": 1]],
  icons.appendingPathComponent("Contents.json"))
try json(
  ["info": ["author": "xcode", "version": 1]], catalog.appendingPathComponent("Contents.json"))
var markImages: [[String: String]] = []
for scale in [1, 2] {
  let filename = "brand-mark\(scale == 2 ? "@2x" : "").png"
  try render(128 * scale, background: false, to: marks.appendingPathComponent(filename))
  markImages.append(["idiom": "universal", "scale": "\(scale)x", "filename": filename])
}
try json(
  ["images": markImages, "info": ["author": "xcode", "version": 1]],
  marks.appendingPathComponent("Contents.json"))
try render(
  1024, background: true, opaque: true,
  to: submission.appendingPathComponent("SuperQode-1024.png"))
try render(
  1024, background: true,
  to: submission.appendingPathComponent("SuperQode-Dock.png"))
let digest = SHA256.hash(data: try Data(contentsOf: source)).map { String(format: "%02x", $0) }
  .joined()
try json(
  [
    "source": "assets/superqode-logo.svg", "source_sha256": digest,
    "rendering":
      "Original SVG mark on a glossy dimensional macOS tile; transparent Dock silhouette; opaque submission preview; native vector rendering at every size",
    "icons": manifest,
  ], submission.appendingPathComponent("manifest.json"))
print(
  "Generated 10 macOS icon slots, a 1024px submission icon and native brand marks from the existing SVG."
)
