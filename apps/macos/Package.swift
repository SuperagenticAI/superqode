// swift-tools-version: 6.0
import PackageDescription

let package = Package(
  name: "SuperQode",
  platforms: [.macOS(.v14)],
  products: [.executable(name: "SuperQode", targets: ["SuperQode"])],
  dependencies: [.package(url: "https://github.com/migueldeicaza/SwiftTerm.git", exact: "1.20.0")],
  targets: [.executableTarget(name: "SuperQode", dependencies: [.product(name: "SwiftTerm", package: "SwiftTerm")])],
  swiftLanguageModes: [.v5]
)
