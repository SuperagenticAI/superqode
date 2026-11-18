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
    Tile(id: "agent", title: "Your agent", detail: "Connect the coding agent you already use.", symbol: "person.crop.circle", page: "menu:root"),
    Tile(id: "harness", title: "SuperQode harness", detail: "Choose a harness for your coding model.", symbol: "sparkles", page: "menu:harness"),
    Tile(id: "local", title: "Local model", detail: "Code with a model in Ollama or LM Studio.", symbol: "desktopcomputer", page: "source:local"),
    Tile(id: "systemone", title: "SystemOne", detail: "Use TypeSafe Jev, Google or OpenAI for decisions.", symbol: "checkmark.shield", page: "systemone"),
    Tile(id: "key", title: "API key", detail: "Your provider key with API billing.", symbol: "key", page: "source:key"),
    Tile(id: "acp", title: "ACP agent", detail: "A coding agent you run as a local process.", symbol: "link", page: "acp"),
    Tile(id: "protocols", title: "Protocols", detail: "Reach an agent over ACP, A2A or UHP.", symbol: "network", page: "menu:protocols"),
    Tile(id: "builder", title: "Build your harness", detail: "Import a config, use presets or start with the wizard.", symbol: "hammer", page: "builder"),
  ]

  var body: some View {
    VStack(alignment: .leading, spacing: 10) {
      tileGrid
      Text("Alibaba Cloud Model Studio is under Your agent. More integrations will follow.")
        .font(.caption).foregroundStyle(.secondary)
        .fixedSize(horizontal: false, vertical: true)
    }
  }

  private var tileGrid: some View {
    LazyVGrid(columns: [GridItem(.adaptive(minimum: 198), spacing: 12, alignment: .top)], spacing: 12) {
      ForEach(Self.tiles) { tile in
        Button { app.openConnections(tile.page) } label: {
          VStack(alignment: .leading, spacing: 6) {
            HStack {
              Image(systemName: tile.symbol).font(.title3).foregroundStyle(Color.qAccent)
              Spacer()
              Image(systemName: "chevron.right").font(.caption).foregroundStyle(.tertiary)
            }
            .accessibilityHidden(true)
            Text(tile.title).font(.headline)
            Text(tile.detail).font(.callout).foregroundStyle(.secondary)
          }
          .multilineTextAlignment(.leading)
          .fixedSize(horizontal: false, vertical: true)
          .padding(12)
          .frame(maxWidth: .infinity, minHeight: 112, alignment: .topLeading)
          .contentShape(Rectangle())
        }
        .buttonStyle(ConnectionChoiceStyle())
        .accessibilityIdentifier("start.tile." + tile.id)
        .accessibilityLabel(tile.title + ". " + tile.detail)
      }
    }.disabled(app.connectionPickerDisabled)
  }
}
