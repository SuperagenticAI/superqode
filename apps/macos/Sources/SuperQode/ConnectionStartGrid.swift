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
  }
  private static let tiles: [Tile] = [
    Tile(id: "agent", title: "Your agent", detail: "Open all connections and choose the agent you already use.", symbol: "person.crop.circle", page: "menu:root"),
    Tile(id: "harness", title: "SuperQode harness", detail: "Core, RLM, PiPy, CodeGem or Workbench with your model.", symbol: "sparkles", page: "menu:harness"),
    Tile(id: "local", title: "Local model", detail: "Pick an installed Ollama or LM Studio model and start coding.", symbol: "desktopcomputer", page: "source:local"),
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
            ConnectionCardLabel(title: tile.title, subtitle: tile.detail) {
              Image(systemName: tile.symbol).font(.title2).foregroundStyle(Color.qAccent).frame(width: 28)
            }
            .frame(height: 80)
          }.buttonStyle(ConnectionChoiceStyle())
            .accessibilityIdentifier("start.tile." + tile.id)
            .accessibilityLabel(tile.title + ". " + tile.detail)
        }
      }
    }.disabled(app.connectionPickerDisabled)
  }
}
