import AppKit
import CoreGraphics
import CryptoKit
import ImageIO
import UniformTypeIdentifiers

// One full-bleed icon for iOS and macOS. The field is black. The system rounds
// it. Light and dark mode use this artwork. A tinted Home Screen uses the same
// shapes in grayscale.
enum SuperQodeIcon {
  enum Appearance {
    case standard
    case tinted
  }

  private static var ink: (minX: CGFloat, minY: CGFloat, maxX: CGFloat, maxY: CGFloat)?

  static func render(logo: NSImage, pixels: Int, appearance: Appearance) -> CGImage {
    let box = measuredInk(logo)
    guard let space = CGColorSpace(name: CGColorSpace.sRGB) else { fatalError("sRGB is unavailable") }
    let rgbx = CGImageAlphaInfo.noneSkipLast.rawValue | CGBitmapInfo.byteOrder32Big.rawValue
    guard let canvas = CGContext(
      data: nil, width: pixels, height: pixels, bitsPerComponent: 8, bytesPerRow: pixels * 4,
      space: space, bitmapInfo: rgbx)
    else { fatalError("Could not prepare the SuperQode icon") }
    let drawing = NSGraphicsContext(cgContext: canvas, flipped: false)
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = drawing
    drawing.imageInterpolation = .high
    canvas.setFillColor(CGColor(srgbRed: 0, green: 0, blue: 0, alpha: 1))
    canvas.fill(CGRect(x: 0, y: 0, width: pixels, height: pixels))
    // The field stays full-bleed. The mark sits inside it so the rounded mask
    // does not crowd the logo.
    let span = CGFloat(pixels) * 0.64
    let inkSpan = max(box.maxX - box.minX, box.maxY - box.minY)
    let drawn = span / inkSpan
    let midX = (box.minX + box.maxX) / 2
    let midY = (box.minY + box.maxY) / 2
    let origin = NSPoint(x: CGFloat(pixels) / 2 - midX * drawn, y: CGFloat(pixels) / 2 - midY * drawn)
    logo.draw(
      in: NSRect(x: origin.x, y: origin.y, width: drawn, height: drawn), from: .zero,
      operation: .sourceOver, fraction: 1)
    NSGraphicsContext.restoreGraphicsState()
    if appearance == .tinted { grayscale(canvas, pixels: pixels) }
    guard let image = canvas.makeImage() else { fatalError("Could not read the SuperQode icon") }
    if pixels >= 1024 { validate(image, pixels: pixels, tinted: appearance == .tinted) }
    return image
  }

  static func write(_ image: CGImage, to url: URL) {
    guard let destination = CGImageDestinationCreateWithURL(
      url as CFURL, UTType.png.identifier as CFString, 1, nil)
    else { fatalError("Could not prepare \(url.lastPathComponent)") }
    CGImageDestinationAddImage(destination, image, nil)
    guard CGImageDestinationFinalize(destination) else {
      fatalError("Could not save \(url.lastPathComponent)")
    }
  }

  private static func measuredInk(_ logo: NSImage) -> (
    minX: CGFloat, minY: CGFloat, maxX: CGFloat, maxY: CGFloat
  ) {
    if let ink { return ink }
    let pixels = 1024
    guard let space = CGColorSpace(name: CGColorSpace.sRGB) else { fatalError("sRGB is unavailable") }
    let rgba = CGImageAlphaInfo.premultipliedLast.rawValue | CGBitmapInfo.byteOrder32Big.rawValue
    guard let measure = CGContext(
      data: nil, width: pixels, height: pixels, bitsPerComponent: 8, bytesPerRow: pixels * 4,
      space: space, bitmapInfo: rgba)
    else { fatalError("Could not measure the SuperQode logo") }
    let context = NSGraphicsContext(cgContext: measure, flipped: false)
    NSGraphicsContext.saveGraphicsState()
    NSGraphicsContext.current = context
    context.imageInterpolation = .high
    logo.draw(
      in: NSRect(x: 0, y: 0, width: pixels, height: pixels), from: .zero,
      operation: .sourceOver, fraction: 1)
    NSGraphicsContext.restoreGraphicsState()
    guard let data = measure.data else { fatalError("Could not read the SuperQode logo") }
    let bytes = data.bindMemory(to: UInt8.self, capacity: pixels * pixels * 4)
    var minX = pixels, minY = pixels, maxX = 0, maxY = 0
    for y in 0..<pixels {
      for x in 0..<pixels where bytes[(y * pixels + x) * 4 + 3] > 12 {
        minX = min(minX, x)
        minY = min(minY, y)
        maxX = max(maxX, x)
        maxY = max(maxY, y)
      }
    }
    guard maxX > minX, maxY > minY else { fatalError("The SuperQode logo has no visible ink") }
    let found = (
      minX: CGFloat(minX) / CGFloat(pixels), minY: CGFloat(minY) / CGFloat(pixels),
      maxX: CGFloat(maxX) / CGFloat(pixels), maxY: CGFloat(maxY) / CGFloat(pixels))
    ink = found
    return found
  }

  private static func grayscale(_ canvas: CGContext, pixels: Int) {
    guard let data = canvas.data else { fatalError("Could not read the tinted icon") }
    let bytes = data.bindMemory(to: UInt8.self, capacity: pixels * pixels * 4)
    for offset in stride(from: 0, to: pixels * pixels * 4, by: 4) {
      let red = Int(bytes[offset])
      let green = Int(bytes[offset + 1])
      let blue = Int(bytes[offset + 2])
      let chroma = max(red, green, blue) - min(red, green, blue)
      let gray: Int
      if chroma < 72 && red < 90 {
        gray = 26
      } else {
        let luminance = (54 * red + 183 * green + 18 * blue) / 255
        gray = min(252, 176 + luminance * 76 / 255)
      }
      let value = UInt8(gray)
      bytes[offset] = value
      bytes[offset + 1] = value
      bytes[offset + 2] = value
    }
  }

  private static func validate(_ image: CGImage, pixels: Int, tinted: Bool) {
    guard image.width == pixels, image.height == pixels, let space = CGColorSpace(name: CGColorSpace.sRGB),
      let canvas = CGContext(
        data: nil, width: pixels, height: pixels, bitsPerComponent: 8, bytesPerRow: pixels * 4,
        space: space, bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue | CGBitmapInfo.byteOrder32Big.rawValue)
    else { fatalError("Could not check the SuperQode icon") }
    canvas.draw(image, in: CGRect(x: 0, y: 0, width: pixels, height: pixels))
    guard let data = canvas.data else { fatalError("Could not check the SuperQode icon") }
    let bytes = data.bindMemory(to: UInt8.self, capacity: pixels * pixels * 4)
    func sample(_ x: Int, _ y: Int) -> (Int, Int, Int) {
      let index = (y * pixels + x) * 4
      return (Int(bytes[index]), Int(bytes[index + 1]), Int(bytes[index + 2]))
    }
    for point in [(1, 1), (pixels - 2, 1), (1, pixels - 2), (pixels - 2, pixels - 2)] {
      let pixel = sample(point.0, point.1)
      if tinted {
        if pixel.0 != pixel.1 || pixel.1 != pixel.2 {
          fatalError("The tinted SuperQode icon must be grayscale")
        }
      } else if pixel != (0, 0, 0) {
        fatalError("The SuperQode icon field must be black to the canvas edge")
      }
    }
    if tinted { return }
    var mark = false
    for y in stride(from: pixels * 3 / 10, to: pixels * 7 / 10, by: 6) {
      for x in stride(from: pixels * 3 / 10, to: pixels * 7 / 10, by: 6) {
        let pixel = sample(x, y)
        if pixel.0 > 160 && pixel.1 < 140 { mark = true }
      }
    }
    guard mark else { fatalError("The SuperQode mark is missing from the icon") }
  }
}

if CommandLine.arguments.count > 2 && CommandLine.arguments[1] == "ios" {
  let root = URL(fileURLWithPath: CommandLine.arguments[2])
  let logoURL = root.deletingLastPathComponent().deletingLastPathComponent()
    .appendingPathComponent("assets/superqode-logo.svg")
  guard let phoneLogo = NSImage(contentsOf: logoURL) else {
    fatalError("The original SuperQode logo could not be read")
  }
  let catalog = root.appendingPathComponent("SuperQode/Assets.xcassets/AppIcon.appiconset")
  let standardURL = catalog.appendingPathComponent("AppIcon.png")
  let darkURL = catalog.appendingPathComponent("AppIcon-Dark.png")
  let tintedURL = catalog.appendingPathComponent("AppIcon-Tinted.png")
  SuperQodeIcon.write(
    SuperQodeIcon.render(logo: phoneLogo, pixels: 1024, appearance: .standard), to: standardURL)
  if FileManager.default.fileExists(atPath: darkURL.path) {
    try FileManager.default.removeItem(at: darkURL)
  }
  try FileManager.default.copyItem(at: standardURL, to: darkURL)
  SuperQodeIcon.write(
    SuperQodeIcon.render(logo: phoneLogo, pixels: 1024, appearance: .tinted), to: tintedURL)
  exit(0)
}

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
  var data = try JSONSerialization.data(withJSONObject: object, options: [.prettyPrinted, .sortedKeys])
  data.append(0x0A)
  try data.write(to: url)
}
func renderMark(_ pixels: Int, to url: URL) throws {
  guard let colorSpace = CGColorSpace(name: CGColorSpace.sRGB),
    let cgContext = CGContext(
      data: nil, width: pixels, height: pixels, bitsPerComponent: 8, bytesPerRow: 0,
      space: colorSpace, bitmapInfo: CGImageAlphaInfo.premultipliedLast.rawValue)
  else { fatalError("Cannot create icon bitmap") }
  let context = NSGraphicsContext(cgContext: cgContext, flipped: false)
  NSGraphicsContext.saveGraphicsState()
  NSGraphicsContext.current = context
  context.imageInterpolation = .high
  let size = CGFloat(pixels)
  logo.draw(
    in: NSRect(x: 0, y: 0, width: size, height: size), from: .zero,
    operation: .sourceOver, fraction: 1)
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
    SuperQodeIcon.write(
      SuperQodeIcon.render(logo: logo, pixels: size * scale, appearance: .standard), to: target)
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
  try renderMark(128 * scale, to: marks.appendingPathComponent(filename))
  markImages.append(["idiom": "universal", "scale": "\(scale)x", "filename": filename])
}
try json(
  ["images": markImages, "info": ["author": "xcode", "version": 1]],
  marks.appendingPathComponent("Contents.json"))
let master = submission.appendingPathComponent("SuperQode-1024.png")
SuperQodeIcon.write(
  SuperQodeIcon.render(logo: logo, pixels: 1024, appearance: .standard), to: master)
let dock = submission.appendingPathComponent("SuperQode-Dock.png")
if FileManager.default.fileExists(atPath: dock.path) { try FileManager.default.removeItem(at: dock) }
try FileManager.default.copyItem(at: master, to: dock)
let phone = root.appendingPathComponent("apps/ios/SuperQode/Assets.xcassets/AppIcon.appiconset")
for name in ["AppIcon.png", "AppIcon-Dark.png"] {
  let destination = phone.appendingPathComponent(name)
  if FileManager.default.fileExists(atPath: destination.path) {
    try FileManager.default.removeItem(at: destination)
  }
  try FileManager.default.copyItem(at: master, to: destination)
}
SuperQodeIcon.write(
  SuperQodeIcon.render(logo: logo, pixels: 1024, appearance: .tinted),
  to: phone.appendingPathComponent("AppIcon-Tinted.png"))
let digest = SHA256.hash(data: try Data(contentsOf: source)).map { String(format: "%02x", $0) }
  .joined()
try json(
  [
    "source": "assets/superqode-logo.svg", "source_sha256": digest,
    "rendering":
      "Original SVG mark on a black full-bleed icon. Light and dark mode use this artwork. The system applies the rounded mask. Native vector rendering at every size",
    "icons": manifest,
  ], submission.appendingPathComponent("manifest.json"))
let iconutil = Process()
iconutil.executableURL = URL(fileURLWithPath: "/usr/bin/iconutil")
iconutil.arguments = [
  "-c", "icns", iconset.path, "-o", app.appendingPathComponent("resources/icon.icns").path,
]
try iconutil.run()
iconutil.waitUntilExit()
guard iconutil.terminationStatus == 0 else { fatalError("Could not build the macOS icon.icns") }
print(
  "Generated 10 macOS icon slots, icon.icns, a 1024px submission icon and native brand marks from the existing SVG."
)
