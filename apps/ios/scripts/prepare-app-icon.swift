import AppKit
import CoreGraphics
import ImageIO
import UniformTypeIdentifiers

// Preserve the existing Mac icon and composite its transparent corners onto black.
// iOS App Store icons require an opaque square; the brand artwork is unchanged.
let root = CommandLine.arguments.count > 1
  ? URL(fileURLWithPath: CommandLine.arguments[1])
  : URL(fileURLWithPath: #filePath).deletingLastPathComponent().deletingLastPathComponent()
let source = root.deletingLastPathComponent()
  .appendingPathComponent("macos/resources/Assets.xcassets/AppIcon.appiconset/icon_512x512@2x.png")
let target = root.appendingPathComponent("SuperQode/Assets.xcassets/AppIcon.appiconset/AppIcon.png")
guard let imageSource = CGImageSourceCreateWithURL(source as CFURL, nil),
  let image = CGImageSourceCreateImageAtIndex(imageSource, 0, nil),
  let space = CGColorSpace(name: CGColorSpace.sRGB),
  let context = CGContext(data: nil, width: 1024, height: 1024, bitsPerComponent: 8,
    bytesPerRow: 4096, space: space, bitmapInfo: CGImageAlphaInfo.noneSkipLast.rawValue)
else { fatalError("The original SuperQode Mac icon could not be read") }
context.setFillColor(CGColor(red: 0, green: 0, blue: 0, alpha: 1))
context.fill(CGRect(x: 0, y: 0, width: 1024, height: 1024))
context.draw(image, in: CGRect(x: 0, y: 0, width: 1024, height: 1024))
guard let opaque = context.makeImage(),
  let output = CGImageDestinationCreateWithURL(target as CFURL, UTType.png.identifier as CFString, 1, nil)
else { fatalError("The iOS icon could not be prepared") }
CGImageDestinationAddImage(output, opaque, nil)
guard CGImageDestinationFinalize(output) else { fatalError("The opaque iOS icon could not be saved") }
