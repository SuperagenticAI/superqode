import SwiftUI

enum ACPAgentFilter: String, CaseIterable, Identifiable {
  case all = "All agents", installed = "On this Mac", verified = "Session ready", custom = "Custom"
  var id: String { rawValue }
}

func filteredACPAgents(_ routes: [[String: Any]], search: String, filter: ACPAgentFilter,
  metadata: [String: [String: Any]], selected: String) -> [[String: Any]] {
  let query = search.trimmingCharacters(in: .whitespacesAndNewlines)
  return routes.filter { route in
    let matches = query.isEmpty || ["name", "description", "id"].map { string(route, $0) }
      .joined(separator: " ").localizedCaseInsensitiveContains(query)
    guard matches else { return false }
    switch filter {
    case .all: return true
    case .installed: return route["available"] as? Bool == true
    case .verified: return verifiedACPConnection(route: route, metadata: metadata[string(route, "id")] ?? [:])
    case .custom: return route["custom"] as? Bool == true
    }
  }.sorted {
    let left = string($0, "id"), right = string($1, "id")
    if (left == selected) != (right == selected) { return left == selected }
    if ($0["available"] as? Bool == true) != ($1["available"] as? Bool == true) { return $0["available"] as? Bool == true }
    let comparison = string($0, "name").localizedStandardCompare(string($1, "name"))
    return comparison == .orderedSame ? left < right : comparison == .orderedAscending
  }
}

struct ACPAgentCatalogView: View {
  @EnvironmentObject var app: Workspace
  let registry: [String: Any]
  @Binding var search: String
  let refreshRegistry: () -> Void
  let addCustom: () -> Void
  let open: ([String: Any]) -> Void
  var initialTab = "agents"
  @State private var tab = "agents"
  @State private var filter = ACPAgentFilter.all
  private var rows: [[String: Any]] {
    filteredACPAgents(app.acpConnections, search: search, filter: filter,
      metadata: app.connectionMetadata, selected: app.harness)
  }
  var body: some View {
    VStack(alignment: .leading, spacing: 20) {
      Picker("Explore ACP", selection: $tab) {
        Text("Connect an agent").tag("agents")
        Text("Clients & ecosystem").tag("clients")
      }.pickerStyle(.segmented).frame(maxWidth: 420)
      if tab == "agents" {
        ConnectionSearchField(title: "Search ACP agents", text: $search)
        HStack {
          Picker("Filter agents", selection: $filter) {
            ForEach(ACPAgentFilter.allCases) { Text($0.rawValue).tag($0) }
          }.pickerStyle(.segmented)
          Text("\(rows.count) agents").font(.caption).foregroundStyle(.secondary).monospacedDigit()
        }
        HStack {
          Button("Refresh installed", systemImage: "arrow.clockwise") { app.perform { try await app.refreshDefinitions() } }
          Button("Refresh registry…", systemImage: "square.and.arrow.down", action: refreshRegistry)
          Spacer()
          Button("Custom agent…", systemImage: "plus", action: addCustom)
        }.controlSize(.small)
        if rows.isEmpty {
          ContentUnavailableView {
            Label("No matching agents", systemImage: "magnifyingglass")
          } description: {
            Text("Try another search or filter, or add your own ACP agent.")
          } actions: {
            Button("Show all agents") { search = ""; filter = .all }
          }.frame(maxWidth: .infinity).padding(.vertical, 24)
        } else {
          LazyVGrid(columns: [GridItem(.adaptive(minimum: 230), spacing: 8)], spacing: 8) {
            ForEach(rows, id: \.projectRowID) { route in
              ACPAgentCard(route: route, metadata: app.connectionMetadata[string(route, "id")] ?? [:],
                selected: app.harness == string(route, "id")) { open(route) }
            }
          }
        }
        VStack(alignment: .leading, spacing: 6) {
          Label("SuperQode is the ACP client. These agents provide the server side of the connection.", systemImage: "link")
          Text("Choose an agent to see its setup steps and check whether it can start an ACP session.")
          Text(string(registry, "source", "Bundled catalog") + ((registry["updated"] as? Double).map {
            " · Updated " + Date(timeIntervalSince1970: $0).formatted(date: .abbreviated, time: .shortened)
          } ?? " · Available offline"))
          if !string(registry, "issue").isEmpty { Text(string(registry, "issue")).foregroundStyle(.orange) }
        }.font(.caption).foregroundStyle(.secondary)
      } else { ACPClientDirectoryView() }
    }.onAppear { tab = initialTab }
  }
}

private struct ACPAgentCard: View {
  let route: [String: Any]
  let metadata: [String: Any]
  let selected: Bool
  let open: () -> Void
  private var verified: Bool { verifiedACPConnection(route: route, metadata: metadata) }
  private var installed: Bool { route["available"] as? Bool == true }
  private var status: String { verified ? "Session ready" : installed ? "Launcher detected" : "Setup required" }
  var body: some View {
    nativeButton("connect.row." + string(route, "id"), action: open, padded: false,
      title: string(route, "name") + ", " + status + ". Open agent setup") {
      ConnectionCardLabel(title: string(route, "name"),
        subtitle: string(route, "description"), status: status) {
        HarnessIcon(identity: HarnessIdentity(route), size: 44)
      }.modifier(ConnectionCardSurface(selected: selected))
    }
      .help(installed ? "Open setup and verify this agent's connection" : string(route, "issue", "Open installation and sign-in instructions"))
  }
}

struct ACPClientDirectoryView: View {
  @State private var search = ""
  @State private var category = "All categories"
  private var categories: [String] { ["All categories"] + Set(ACPClientDirectory.projects.map(\.category)).sorted() }
  private var projects: [ACPClientProject] {
    ACPClientDirectory.projects.filter {
      (category == "All categories" || $0.category == category) &&
        (search.isEmpty || ($0.name + " " + $0.category).localizedCaseInsensitiveContains(search))
    }
  }
  var body: some View {
    VStack(alignment: .leading, spacing: 18) {
      HStack(spacing: 12) {
        HarnessIcon(identity: HarnessIdentity(["id": "core", "name": "SuperQode"]), size: 44)
        VStack(alignment: .leading, spacing: 4) {
          Text("Your ACP client is SuperQode").font(.headline)
          Text("Connect agent servers in the other tab. Explore clients, frameworks and connectors below.")
            .font(.callout).foregroundStyle(.secondary)
        }
      }.padding(16).brandSurface()
      HStack {
        TextField("Search the ACP ecosystem", text: $search).textFieldStyle(.roundedBorder)
        Picker("Category", selection: $category) {
          ForEach(categories, id: \.self) { Text($0).tag($0) }
        }.frame(width: 200)
      }
      HStack {
        Text("\(projects.count) projects · Snapshot: " + ACPClientDirectory.snapshotDate).font(.caption).foregroundStyle(.secondary)
        Spacer()
        Link("Current official directory ↗", destination: URL(string: ACPClientDirectory.source)!)
      }
      LazyVGrid(columns: [GridItem(.adaptive(minimum: 220, maximum: 400), spacing: 14)], spacing: 14) {
        ForEach(projects) { project in
          if let url = URL(string: project.url) {
            Link(destination: url) {
              VStack(alignment: .leading, spacing: 12) {
                HStack {
                  Image(systemName: "app.connected.to.app.below.fill").font(.title2).foregroundStyle(.secondary)
                  Spacer()
                  Image(systemName: "arrow.up.right").font(.caption).foregroundStyle(.secondary)
                }
                Text(project.name).font(.headline).lineLimit(2)
                Text(project.category).font(.caption).foregroundStyle(.secondary)
                Text(url.host ?? "Project website").font(.caption).foregroundStyle(.secondary).lineLimit(1)
              }.padding(18).frame(maxWidth: .infinity, alignment: .leading).frame(height: 154).brandSurface()
                .contentShape(Rectangle())
            }.buttonStyle(.plain).help("Open " + project.name + " website")
          }
        }
      }
      if projects.isEmpty { ContentUnavailableView.search(text: search) }
      Text("The official directory includes ACP clients and related tools. These links open project websites; they are not agent connections or verified integrations with SuperQode.")
        .font(.caption).foregroundStyle(.secondary)
    }
  }
}
