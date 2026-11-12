// swift-tools-version: 6.0
import PackageDescription

let package = Package(
  name: "SuperQode",
  platforms: [.macOS(.v14)],
  products: [.executable(name: "SuperQode", targets: ["SuperQode"]),
    .executable(name: "SuperQodeAppleModel", targets: ["SuperQodeAppleModel"])],
  dependencies: [.package(url: "https://github.com/migueldeicaza/SwiftTerm.git", exact: "1.20.0")],
  targets: [
    .executableTarget(name: "SuperQode", dependencies: [.product(name: "SwiftTerm", package: "SwiftTerm")]),
    .executableTarget(name: "SuperQodeAppleModel", linkerSettings: [
      .unsafeFlags(["-Xlinker", "-weak_framework", "-Xlinker", "FoundationModels"], .when(platforms: [.macOS])),
    ]),
    .testTarget(name: "SuperQodeTests", dependencies: ["SuperQode"]),
    .testTarget(name: "SuperQodeAppleModelTests", dependencies: ["SuperQodeAppleModel"]),
  ],
  swiftLanguageModes: [.v5]
)
