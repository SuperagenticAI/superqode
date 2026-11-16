import SwiftUI

/// Whether a Harness Studio draft uses the Silicon profile. The service checks again.
func isSiliconDraft(_ text: String) -> Bool {
  text.range(of: #"(?m)^\s*profile:\s*['"]?silicon['"]?\s*$"#, options: .regularExpression) != nil
}

struct SiliconCheckForm: Identifiable, Equatable {
  var index: Int
  var name: String
  var command: String
  var container: Bool
  var image: String
  var files: String
  var original: Bool
  var originalImage: String
  var originalFiles: String
  var id: Int { index }
  var changed: Bool { container != original || (container && (image != originalImage || files != originalFiles)) }
  var fileList: [String] {
    files.split(whereSeparator: { $0 == "," || $0 == "\n" })
      .map { $0.trimmingCharacters(in: .whitespaces) }.filter { !$0.isEmpty }
  }
}

/// Edits Silicon MCP, Monty Code Mode and Apple Container checks in the draft.
/// The YAML draft stays the source of truth: the service returns an edited draft
/// and a diff, and Studio's Validate and Save revision steps still apply.
struct SiliconOptionsView: View {
  @EnvironmentObject var app: Workspace
  @DialogDismiss private var dismiss
  let project: String
  let name: String
  let yaml: String
  let onApply: (String) -> Void

  @State private var state: [String: Any] = [:]
  @State private var loaded = false
  @State private var busy = false
  @State private var failure = ""
  @State private var mcpOn = false
  @State private var initialMCP = false
  @State private var servers: [String] = []
  @State private var chosen: Set<String> = []
  @State private var toolText: [String: String] = [:]
  @State private var initialAllowlist: [String: String] = [:]
  @State private var codeMode = false
  @State private var initialCodeMode = false
  @State private var failOnError = false
  @State private var initialFailOnError = false
  @State private var checks: [SiliconCheckForm] = []
  @State private var newName = ""
  @State private var newCommand = ""
  @State private var preview: [String: Any] = [:]

  private var support: [String: Any] { state["support"] as? [String: Any] ?? [:] }
  private var container: [String: Any] { support["apple_container"] as? [String: Any] ?? [:] }
  private var monty: [String: Any] { support["monty"] as? [String: Any] ?? [:] }
  private var containerReady: Bool { container["available"] as? Bool == true }
  private var montyReady: Bool { monty["available"] as? Bool == true }
  private var baseTools: [String] { (state["tools"] as? [String] ?? []).filter { $0 != "execute" } }
  private var toolCount: Int { baseTools.count + (mcpOn ? 1 : 0) }
  private var toolLimit: Int { state["tool_limit"] as? Int ?? 5 }
  private var allowlist: [String: [String]] {
    var result: [String: [String]] = [:]
    for server in chosen.sorted() {
      result[server] = (toolText[server] ?? "").split(separator: ",")
        .map { $0.trimmingCharacters(in: .whitespaces) }.filter { !$0.isEmpty }
    }
    return result
  }
  private var allowlistChanged: Bool {
    Dictionary(uniqueKeysWithValues: chosen.map { ($0, toolText[$0] ?? "") }) != initialAllowlist
  }
  private var formKey: String {
    let tools = toolText.keys.sorted().map { $0 + "=" + (toolText[$0] ?? "") }.joined(separator: ";")
    let rows = checks.map { "\($0.index)|\($0.container)|\($0.image)|\($0.files)" }.joined(separator: ";")
    let parts: [String] = [String(mcpOn), chosen.sorted().joined(separator: ","), tools,
      String(codeMode), String(failOnError), newName, newCommand, rows]
    return parts.joined(separator: "\n")
  }
  private var options: [String: Any] {
    var result: [String: Any] = [:]
    if mcpOn != initialMCP || (mcpOn && allowlistChanged) {
      var mcp: [String: Any] = ["enabled": mcpOn]
      if mcpOn { mcp["allowlist"] = allowlist }
      result["mcp"] = mcp
    }
    if codeMode != initialCodeMode || (!mcpOn && initialCodeMode) { result["code_mode"] = mcpOn && codeMode }
    var checkOptions: [String: Any] = [:]
    if failOnError != initialFailOnError { checkOptions["fail_on_error"] = failOnError }
    var steps: [[String: Any]] = []
    for check in checks where check.changed {
      var step: [String: Any] = ["index": check.index, "apple_container": check.container]
      if check.container {
        step["image"] = check.image.trimmingCharacters(in: .whitespaces)
        step["files"] = check.fileList
      }
      steps.append(step)
    }
    if !steps.isEmpty { checkOptions["steps"] = steps }
    let trimmedName = newName.trimmingCharacters(in: .whitespaces)
    let trimmedCommand = newCommand.trimmingCharacters(in: .whitespaces)
    if !trimmedName.isEmpty && !trimmedCommand.isEmpty {
      let added: [String: Any] = ["name": trimmedName, "command": trimmedCommand, "timeout": 60]
      checkOptions["add"] = [added]
    }
    if !checkOptions.isEmpty { result["checks"] = checkOptions }
    return result
  }

  var body: some View {
    VStack(alignment: .leading, spacing: 14) {
      Text("Silicon options").font(.title2)
      Text("These switches edit the harness draft. Review the changes, then validate and save the revision as usual.")
        .font(.callout).foregroundStyle(.secondary)
      if !loaded && failure.isEmpty { ProgressView().controlSize(.small) }
      if loaded {
        ScrollView {
          VStack(alignment: .leading, spacing: 18) {
            toolBudget
            mcpSection
            codeModeSection
            checksSection
            previewSection
          }.frame(maxWidth: .infinity, alignment: .leading)
        }
      }
      if !failure.isEmpty { Text(failure).foregroundStyle(.orange).textSelection(.enabled) }
      HStack {
        Button("Cancel") { dismiss() }.keyboardShortcut(.cancelAction)
        Spacer()
        if busy { ProgressView().controlSize(.small) }
        Button("Preview changes") { runPreview() }.disabled(!loaded || busy || options.isEmpty)
        Button("Apply to draft") {
          onApply(string(preview, "yaml")); dismiss()
        }.buttonStyle(BrandButtonStyle()).disabled(busy || preview["changed"] as? Bool != true)
      }
    }.padding(24).frame(width: 760, height: 640)
      .task { await load() }
      .onChange(of: formKey) { _, _ in preview = [:] }
  }

  private var toolBudget: some View {
    VStack(alignment: .leading, spacing: 4) {
      Text("Apple tool budget · \(toolCount) of \(toolLimit)").font(.headline)
      Text("Tools: " + (baseTools + (mcpOn ? ["execute"] : [])).joined(separator: ", ")).font(.caption.monospaced())
      if toolCount > toolLimit {
        Text("Apple on-device runs allow at most \(toolLimit) tools. Remove a tool in the YAML before using this harness with the Apple model.")
          .font(.caption).foregroundStyle(.orange)
      }
    }
  }

  private var mcpSection: some View {
    VStack(alignment: .leading, spacing: 8) {
      Toggle("Use MCP servers", isOn: $mcpOn)
        .disabled(servers.isEmpty && !initialMCP)
        .help("Adds the execute tool, allows network access, and lets the model call only the MCP tools you list.")
      Text(servers.isEmpty
        ? "No MCP servers are configured for this project. Add one in .superqode/mcp.json first."
        : "Off by default. When on, the model can search the listed MCP tools and call one with execute. Adding execute uses one tool slot.")
        .font(.caption).foregroundStyle(.secondary)
      if mcpOn {
        ForEach(servers, id: \.self) { server in
          HStack(alignment: .firstTextBaseline) {
            Toggle(server, isOn: Binding(
              get: { chosen.contains(server) },
              set: { if $0 { chosen.insert(server) } else { chosen.remove(server) } })).toggleStyle(.checkbox).frame(width: 180, alignment: .leading)
            TextField("Tool names, comma separated", text: Binding(
              get: { toolText[server] ?? "" }, set: { toolText[server] = $0 }))
              .textFieldStyle(.roundedBorder).disabled(!chosen.contains(server))
          }
        }
        Text("Enter the exact tool names this server provides. SuperQode adds an allow rule for each one.")
          .font(.caption).foregroundStyle(.secondary)
      }
    }
  }

  private var codeModeSection: some View {
    VStack(alignment: .leading, spacing: 6) {
      Toggle("Monty Code Mode", isOn: $codeMode)
        .disabled(!(mcpOn && (montyReady || initialCodeMode)))
        .help("Experimental. The model writes a short Python snippet that runs in Monty and makes one MCP call.")
      Text(!mcpOn ? "Turn on MCP to use Monty Code Mode."
        : !montyReady ? string(monty, "reason", "Monty is not available.")
        : "Experimental. Uses the same two tools. Each snippet can make one permitted MCP call.")
        .font(.caption).foregroundStyle(.secondary)
    }
  }

  private var checksSection: some View {
    VStack(alignment: .leading, spacing: 8) {
      Text("Checks after each turn").font(.headline)
      Toggle("Fail the run when a check fails", isOn: $failOnError)
      if !containerReady { Text(string(container, "reason")).font(.caption).foregroundStyle(.secondary) }
      ForEach($checks) { $check in
        VStack(alignment: .leading, spacing: 6) {
          Text(check.name).font(.callout.bold())
          Text(check.command).font(.caption.monospaced()).foregroundStyle(.secondary)
          Toggle("Run in Apple Container", isOn: $check.container)
            .disabled(!containerReady && !check.original)
            .help("Runs this check in a disposable Linux container with no network. Use it only for checks that work on Linux.")
          if check.container {
            TextField("Local ARM64 image pinned by digest (name@sha256:…)", text: $check.image).textFieldStyle(.roundedBorder)
            TextField("Project files to copy, comma separated", text: $check.files).textFieldStyle(.roundedBorder)
            Text("The image must already be in the local Apple Container cache. Only the listed files are copied in.")
              .font(.caption).foregroundStyle(.secondary)
          }
        }.padding(12).brandSurface()
      }
      DisclosureGroup("Add a check") {
        VStack(alignment: .leading, spacing: 6) {
          TextField("Check name", text: $newName).textFieldStyle(.roundedBorder)
          TextField("Command, for example python3 verify.py", text: $newCommand).textFieldStyle(.roundedBorder)
          Text("Runs in the local sandbox after each turn with a 60 second limit. Preview and apply, then reopen these options to move it into Apple Container.")
            .font(.caption).foregroundStyle(.secondary)
        }.padding(.top, 6)
      }
    }
  }

  @ViewBuilder private var previewSection: some View {
    if !preview.isEmpty {
      Divider()
      Text("Changes to the draft").font(.headline)
      ForEach((preview["state"] as? [String: Any])?["warnings"] as? [String] ?? [], id: \.self) {
        Text($0).font(.caption).foregroundStyle(.orange)
      }
      if preview["changed"] as? Bool == true {
        CodeBlock(text: string(preview, "diff")).frame(height: 200)
      } else {
        Text("These settings match the current draft.").font(.caption).foregroundStyle(.secondary)
      }
    }
  }

  private func load() async {
    do {
      let result = try await app.engine.call("studio.silicon.options", ["project": project, "yaml": yaml]) as? [String: Any] ?? [:]
      guard !Task.isCancelled else { return }
      state = result
      let mcp = result["mcp"] as? [String: Any] ?? [:]
      servers = (mcp["servers"] as? [[String: Any]] ?? []).map { string($0, "id") }
      let current = mcp["allowlist"] as? [String: [String]] ?? [:]
      for (server, tools) in current { toolText[server] = tools.joined(separator: ", ") }
      for server in current.keys where !servers.contains(server) { servers.append(server) }
      chosen = Set(current.keys)
      initialAllowlist = toolText
      mcpOn = mcp["enabled"] as? Bool == true; initialMCP = mcpOn
      codeMode = result["code_mode"] as? Bool == true; initialCodeMode = codeMode
      let checkState = result["checks"] as? [String: Any] ?? [:]
      failOnError = checkState["fail_on_error"] as? Bool == true; initialFailOnError = failOnError
      checks = (checkState["steps"] as? [[String: Any]] ?? []).map { row in
        let files = (row["files"] as? [String] ?? []).joined(separator: ", ")
        let enabled = row["apple_container"] as? Bool == true
        return SiliconCheckForm(index: row["index"] as? Int ?? 0, name: string(row, "name"), command: string(row, "command"),
          container: enabled, image: string(row, "image"), files: files,
          original: enabled, originalImage: string(row, "image"), originalFiles: files)
      }
      loaded = true; failure = ""
    } catch { if !Task.isCancelled { failure = error.localizedDescription } }
  }

  private func runPreview() {
    let request = options; let key = formKey
    busy = true; failure = ""
    Task {
      defer { busy = false }
      do {
        let result = try await app.engine.call("studio.silicon.apply", ["project": project, "name": name, "yaml": yaml, "options": request]) as? [String: Any] ?? [:]
        guard key == formKey else { return }
        preview = result
      } catch { failure = error.localizedDescription }
    }
  }
}
