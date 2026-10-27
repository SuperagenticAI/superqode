import AppKit
import SwiftUI

/// Native forms backed by the installed engine's typed command definitions.
struct ToolsView: View {
  @EnvironmentObject var app: Workspace
  let workflow: String?
  init(workflow: String? = nil) {
    self.workflow = workflow
    _category = State(initialValue: workflow?.components(separatedBy: " ").first ?? "work")
  }
  @State private var catalog: [[String: Any]] = []
  @State private var query = ""
  @State private var category = "work"
  @State private var selected = ""
  @State private var inputs: [String: String] = [:]
  @State private var flags: [String: Bool] = [:]
  @State private var failure = ""
  @State private var preparing = false
  @State private var showWorkBoard = false
  private let categories = [
    "work": "WorkOrders", "harness": "Harness workflows", "memory": "Memory", "mcp": "MCP servers",
    "skills": "Skills", "skillopt": "Skill optimization", "optimize": "Optimization",
    "local": "Local engines", "models": "Model registry", "runtime": "Runtime diagnostics",
    "providers": "Providers", "policy": "Policy", "profiles": "Profiles", "sandbox": "Sandboxes",
    "trust": "Project trust", "sessions": "Sessions", "benchmark": "Benchmarks",
    "gauge": "Quality gauges",
    "doctor": "Diagnostics", "agents": "Agents", "factory": "Agent factory", "plugins": "Plugins",
    "tools": "Tool registry", "a2a-keys": "A2A credentials",
  ]
  private var action: [String: Any] { catalog.first { string($0, "id") == selected } ?? [:] }
  private var values: [String: Any] {
    var result: [String: Any] = [:]
    for field in action["fields"] as? [[String: Any]] ?? [] {
      let id = string(field, "id")
      if field["boolean"] as? Bool == true {
        result[id] = flags[id] ?? false
      } else if let value = inputs[id], !value.isEmpty {
        result[id] =
          field["multiple"] as? Bool == true
          ? value.components(separatedBy: "\n").filter { !$0.isEmpty } : value
      }
    }
    return result
  }
  var body: some View {
    VStack(alignment: .leading, spacing: 20) {
      PageTitle(
        eyebrow: "Beyond the coding loop", title: "Tools and workflows",
        subtitle:
          "Manage WorkOrders, memory, skills and MCP. Run refinement, promotion, benchmarks and optimization with the installed engine’s native forms."
      )
      HSplitView {
        VStack(alignment: .leading, spacing: 14) {
          Picker("Area", selection: $category) {
            ForEach(categories.keys.sorted(), id: \.self) { Text(categories[$0]!).tag($0) }
          }.labelsHidden()
          if category == "work" {
            Button("Live WorkOrder board…") { showWorkBoard = true }.buttonStyle(BrandButtonStyle())
          }
          TextField("Find a workflow", text: $query).textFieldStyle(.roundedBorder)
          ScrollView {
            LazyVStack(alignment: .leading, spacing: 8) {
              ForEach(
                catalog.filter {
                  string($0, "category") == category
                    && (query.isEmpty
                      || (string($0, "name") + " " + string($0, "description"))
                        .localizedCaseInsensitiveContains(query))
                }, id: \.projectRowID
              ) { row in
                Button {
                  choose(row)
                } label: {
                  VStack(alignment: .leading, spacing: 5) {
                    Text(string(row, "name")).font(.system(size: 12, weight: .semibold))
                    Text(string(row, "description")).font(.caption).foregroundStyle(.secondary)
                      .lineLimit(2)
                  }.padding(12).frame(maxWidth: .infinity, alignment: .leading).background(
                    selected == string(row, "id")
                      ? Color.qAccent.opacity(0.15) : .primary.opacity(0.03),
                    in: RoundedRectangle(cornerRadius: 10))
                }.buttonStyle(.plain)
              }
            }
          }.defaultScrollAnchor(.top)
        }.frame(minWidth: 210, idealWidth: 250, maxWidth: 310).padding(.trailing, 14)
        VStack(alignment: .leading, spacing: 0) {
          if selected.isEmpty {
            EmptyState(
              icon: "wrench.and.screwdriver", title: "Choose a workflow",
              detail:
                "Only the selected workflow’s inputs are shown. Actions run on this Mac with streamed output and recorded exit status."
            )
          } else {
            ScrollView {
              VStack(alignment: .leading, spacing: 18) {
                Text(string(action, "name")).font(.title2.weight(.semibold))
                Text(string(action, "description")).font(.callout).foregroundStyle(.secondary)
                  .textSelection(.enabled)
                if selected == "harness tune" {
                  Text("Use labeled examples and explicitly enable live execution to start tuning. Interactive annotation of unlabeled examples is available in the terminal workflow.")
                    .font(.callout).foregroundStyle(.secondary)
                }
                ForEach(action["fields"] as? [[String: Any]] ?? [], id: \.projectRowID) { field in
                  fieldView(field)
                }
                if !failure.isEmpty {
                  Text(failure).foregroundStyle(.orange).textSelection(.enabled)
                }
                HStack {
                  Button("Review and run") { run() }.buttonStyle(BrandButtonStyle()).disabled(
                    preparing || app.anyActive)
                  if app.active && string(app.detail, "kind") == "tool" {
                    Button("Stop", role: .destructive, action: app.cancel)
                  }
                  Spacer()
                }
                Text(
                  "Actions use the current project and configured providers. Review the action and its budgets before running; live model workflows can incur provider charges."
                ).font(.caption).foregroundStyle(.secondary)
              }.padding(18)
            }.defaultScrollAnchor(.top).id(selected)
          }
          if string(app.detail, "kind") == "tool" {
            Divider()
            EventStream().frame(minHeight: 180, idealHeight: 260, maxHeight: 360)
          }
        }.frame(minWidth: 420, maxWidth: .infinity)
      }
    }.centeredDialog(isPresented: $showWorkBoard, title: "WorkOrders") {
      WorkOrderBoardView().environmentObject(app)
    }
    .padding(26).onChange(of: category) { _, _ in
      selected = ""
      inputs = [:]
      flags = [:]
      failure = ""
    }.task {
      do {
        catalog = try await app.engine.call("tools.catalog") as? [[String: Any]] ?? []
        if let workflow, let row = catalog.first(where: { string($0, "id") == workflow }) {
          choose(row)
        }
      } catch {
        failure = error.localizedDescription
      }
    }
  }
  @ViewBuilder private func fieldView(_ field: [String: Any]) -> some View {
    let id = string(field, "id")
    let title = string(field, "label") + (field["required"] as? Bool == true ? " *" : "")
    VStack(alignment: .leading, spacing: 6) {
      if field["boolean"] as? Bool == true {
        Toggle(title, isOn: Binding(get: { flags[id] ?? false }, set: { flags[id] = $0 }))
      } else {
        Text(title).font(.system(size: 11, weight: .semibold))
        let binding = Binding(get: { inputs[id] ?? "" }, set: { inputs[id] = $0 })
        if field["secret"] as? Bool == true {
          SecureField(title, text: binding).textFieldStyle(.roundedBorder)
        } else if !(field["choices"] as? [String] ?? []).isEmpty {
          Picker(title, selection: binding) {
            Text("Use command default").tag("")
            ForEach(field["choices"] as? [String] ?? [], id: \.self) { Text($0).tag($0) }
          }.labelsHidden()
        } else if field["multiple"] as? Bool == true {
          TextEditor(text: binding).font(.system(size: 12, design: .monospaced)).frame(height: 65)
            .padding(6).brandSurface(radius: 8)
          Text("One value per line. Spaces remain part of the value.").font(.caption2)
            .foregroundStyle(.secondary)
        } else {
          HStack {
            TextField(title, text: binding).textFieldStyle(.roundedBorder)
            if field["path"] as? Bool == true {
              Button {
                let panel = NSOpenPanel()
                panel.canChooseFiles = field["file"] as? Bool ?? true
                panel.canChooseDirectories = field["directory"] as? Bool ?? false
                if panel.runModal() == .OK, let url = panel.url { inputs[id] = url.path }
              } label: {
                Image(systemName: "folder")
              }
            }
          }
        }
      }
      if !string(field, "help").isEmpty {
        Text(string(field, "help")).font(.caption).foregroundStyle(.secondary).fixedSize(
          horizontal: false, vertical: true)
      }
    }
  }
  private func choose(_ row: [String: Any]) {
    selected = string(row, "id")
    inputs = [:]
    flags = [:]
    failure = ""
    for field in row["fields"] as? [[String: Any]] ?? [] {
      let id = string(field, "id")
      if field["boolean"] as? Bool == true {
        flags[id] = field["default"] as? Bool ?? false
      } else if let value = field["default"], !(value is NSNull) {
        inputs[id] =
          (value as? [Any])?.map { String(describing: $0) }.joined(separator: "\n")
          ?? String(describing: value)
      }
      let name = string(field, "name")
      if name == "provider" && !app.isManaged { inputs[id] = app.provider }
      if name == "model" && !app.isManaged && !app.model.isEmpty { inputs[id] = app.model }
      if !app.isManaged && (field["default"] == nil || field["default"] is NSNull) {
        if name == "harness" { inputs[id] = app.harness }
        if ["spec", "spec_path", "spec_option"].contains(name),
          let definition = app.harnesses.first(where: { string($0, "id") == app.harness }),
          !string(definition, "path").isEmpty
        {
          inputs[id] = string(definition, "path")
        }
      }
      // The subprocess has no interactive annotation prompt. Labeled datasets
      // and explicit live consent are still required by the shared tune service.
      if selected == "harness tune", name == "json_output" { flags[id] = true }
    }
  }
  private func run() {
    preparing = true
    failure = ""
    Task {
      defer { preparing = false }
      do {
        let result =
          try await app.engine.call("tools.prepare", ["action": selected, "values": values])
          as? [String: Any] ?? [:]
        guard
          app.confirm(
            "Run " + string(result, "title") + "?",
            "Project: " + string(app.project, "path") + "\n\n" + pretty(result["argv"])
              + "\n\nThis action uses the selected workflow’s permissions, providers and budgets.",
            button: "Run workflow")
        else { return }
        app.start("tools.start", extra: ["action": selected, "values": values])
      } catch { failure = error.localizedDescription }
    }
  }
}
