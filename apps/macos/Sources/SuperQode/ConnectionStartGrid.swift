import SwiftUI

/// A front door to existing connection workflows, without changing a route
/// until the user explicitly chooses one in Connect.
struct ConnectionStartGrid: View {
  @EnvironmentObject var app: Workspace
  private struct Tile: Identifiable {
    let id: String
    let title: String
    let detail: String
    let symbol: String
    let page: String
    var recommended = false
  }
  private static let tiles: [Tile] = [
    Tile(id: "agent", title: "Your agent", detail: "An existing harness with its own tools, model and sign-in.", symbol: "person.crop.circle", page: "menu:agents"),
    Tile(id: "harness", title: "SuperQode harness", detail: "Core, RLM, PiPy, CodeGem or Workbench with your model.", symbol: "sparkles", page: "menu:harness", recommended: true),
    Tile(id: "local", title: "Local model", detail: "Run on your Mac with Ollama or LM Studio.", symbol: "desktopcomputer", page: "source:local"),
    Tile(id: "key", title: "API key", detail: "Your provider key with API billing.", symbol: "key", page: "source:key"),
    Tile(id: "acp", title: "ACP agent", detail: "A coding agent you run as a local process.", symbol: "link", page: "acp"),
    Tile(id: "protocols", title: "Protocols", detail: "Reach an agent over ACP, A2A or UHP.", symbol: "network", page: "menu:protocols"),
    Tile(id: "builder", title: "Build your harness", detail: "Import a config, use presets or start with the wizard.", symbol: "hammer", page: "builder"),
    Tile(id: "systemone", title: "SystemOne", detail: "Typed decisions with Jev from TypeSafe AI.", symbol: "checkmark.shield", page: "systemone"),
  ]

  var body: some View {
    VStack(spacing: 10) {
      LazyVGrid(columns: [GridItem(.adaptive(minimum: 180), spacing: 10)], spacing: 10) {
        ForEach(Self.tiles) { tile in
          Button { app.openConnections(tile.page) } label: {
            VStack(alignment: .leading, spacing: 4) {
              HStack {
                Image(systemName: tile.symbol).foregroundStyle(Color.qAccent)
                Spacer(minLength: 0)
                if tile.recommended { Text("Recommended").font(.caption2).foregroundStyle(.secondary) }
              }
              Text(tile.title).font(.system(size: 13, weight: .semibold))
              Text(tile.detail).font(.caption).foregroundStyle(.secondary)
                .lineLimit(2).fixedSize(horizontal: false, vertical: true)
            }.padding(10).frame(maxWidth: .infinity, minHeight: 84, alignment: .topLeading)
              .background(Color.primary.opacity(0.04), in: RoundedRectangle(cornerRadius: 10))
              .overlay(RoundedRectangle(cornerRadius: 10).stroke(Color.secondary.opacity(0.25)))
              .contentShape(RoundedRectangle(cornerRadius: 10))
          }.buttonStyle(.plain).focusable()
            .accessibilityIdentifier("start.tile." + tile.id)
            .accessibilityLabel(tile.title + ". " + tile.detail)
        }
      }
      Button("All connections and runtimes…") { app.openConnections("menu:root") }
        .accessibilityIdentifier("start.allConnections")
    }.disabled(app.connectionPickerDisabled)
  }
}
