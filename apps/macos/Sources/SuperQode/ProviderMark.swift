import AppKit
import SwiftUI

/// Provider logo on an API-key button. Colour marks stay as drawn. Single-colour
/// marks follow light and dark appearances.
struct ProviderMark: View {
  let providerID: String

  var body: some View {
    if let mark = ProviderMarks.mark(providerID), let image = NSImage(named: mark.asset) {
      Image(nsImage: image)
        .renderingMode(mark.keepsColour ? .original : .template)
        .resizable()
        .scaledToFit()
        .foregroundStyle(.primary)
    } else {
      Image(systemName: "square.grid.2x2")
        .resizable()
        .scaledToFit()
        .foregroundStyle(.secondary)
    }
  }
}

enum ProviderMarks {
  struct Mark {
    let asset: String
    let keepsColour: Bool
  }

  private static let marks: [String: Mark] = [
    "google": Mark(asset: "Provider-google", keepsColour: true),
    "anthropic": Mark(asset: "Provider-anthropic", keepsColour: true),
    "openai": Mark(asset: "Provider-openai", keepsColour: false),
    "xai": Mark(asset: "Provider-xai", keepsColour: false),
    "meta": Mark(asset: "Provider-meta", keepsColour: true),
    "nvidia": Mark(asset: "Provider-nvidia", keepsColour: true),
    "poolside": Mark(asset: "Provider-poolside", keepsColour: false),
    "mistral": Mark(asset: "Provider-mistral", keepsColour: true),
    "deepseek": Mark(asset: "Provider-deepseek", keepsColour: true),
    "qwen-cn": Mark(asset: "Provider-qwen", keepsColour: true),
    "qwen-intl": Mark(asset: "Provider-qwen", keepsColour: true),
    "alibaba": Mark(asset: "Provider-alibaba", keepsColour: true),
    "moonshot": Mark(asset: "Provider-moonshot", keepsColour: false),
    "zai": Mark(asset: "Provider-zai", keepsColour: false),
    "zhipu": Mark(asset: "Provider-zhipu", keepsColour: true),
    "minimax": Mark(asset: "Provider-minimax", keepsColour: true),
    "doubao": Mark(asset: "Provider-doubao", keepsColour: true),
    "baidu": Mark(asset: "Provider-baidu", keepsColour: true),
    "siliconflow": Mark(asset: "Provider-siliconflow", keepsColour: true),
    "baseten": Mark(asset: "Provider-baseten", keepsColour: false),
    "fireworks": Mark(asset: "Provider-fireworks", keepsColour: true),
    "together": Mark(asset: "Provider-together", keepsColour: true),
    "modal": Mark(asset: "Provider-modal", keepsColour: false),
    "openrouter": Mark(asset: "Provider-openrouter", keepsColour: false),
    "groq": Mark(asset: "Provider-groq", keepsColour: false),
    "huggingface": Mark(asset: "Provider-huggingface", keepsColour: true),
    "cerebras": Mark(asset: "Provider-cerebras", keepsColour: true),
    "perplexity": Mark(asset: "Provider-perplexity", keepsColour: true),
    "cohere": Mark(asset: "Provider-cohere", keepsColour: true),
    "opencode": Mark(asset: "Provider-opencode", keepsColour: false),
    "amazon-bedrock": Mark(asset: "Provider-amazon-bedrock", keepsColour: true),
    "azure": Mark(asset: "Provider-azure", keepsColour: true),
    "vertex": Mark(asset: "Provider-google", keepsColour: true),
    "cloudflare": Mark(asset: "Provider-cloudflare", keepsColour: true),
  ]

  static func mark(_ id: String) -> Mark? { marks[id] }
}
