// swift-tools-version: 6.2
import PackageDescription

let package = Package(
  name: "SuperQodeSwiftMLX",
  platforms: [.macOS("27.0")],
  dependencies: [
    .package(url: "https://github.com/ml-explore/mlx-swift-lm", exact: "3.32.3"),
    .package(url: "https://github.com/huggingface/swift-transformers", exact: "1.3.0"),
  ],
  targets: [
    .executableTarget(name: "SuperQodeSwiftMLX", dependencies: [
      .product(name: "MLXLLM", package: "mlx-swift-lm"),
      .product(name: "MLXLMCommon", package: "mlx-swift-lm"),
      .product(name: "MLXHuggingFace", package: "mlx-swift-lm"),
      .product(name: "Tokenizers", package: "swift-transformers"),
    ])
  ]
)
