import SwiftUI

struct LocalModelCompatibilityView: View {
  @EnvironmentObject var app: Workspace
  @DialogDismiss private var dismiss
  let project: String
  @State private var report: [String: Any] = [:]
  @State private var query = ""
  @State private var failure = ""
  @State private var output: String?
  @State private var closed = false
  private var rows: [[String: Any]] {
    (report["backends"] as? [[String: Any]] ?? []).filter {
      query.isEmpty || (string($0, "display_name") + " " + string($0, "backend")).localizedCaseInsensitiveContains(query)
    }
  }
  var body: some View {
    VStack(alignment: .leading, spacing: 16) {
      Text("Local harness compatibility").font(.title2.weight(.semibold))
      Text(string(report, "note", "Loading registered runtimes…")).font(.callout).foregroundStyle(.secondary)
      TextField("Find a runtime or harness backend", text: $query).textFieldStyle(.plain).padding(8).outlinedSurface(radius: 7)
      ScrollView {
        VStack(alignment: .leading, spacing: 14) {
          if let checks = report["checks"] as? [[String: Any]], !checks.isEmpty {
            Text("Recorded model readiness checks").font(.headline)
            ForEach(checks, id: \.projectRowID) { row in
              let result = row["result"] as? [String: Any] ?? [:]
              let verification = result["verification"] as? [String: Any] ?? [:]
              HStack {
                VStack(alignment: .leading) {
                  Text(string(result, "model")).font(.headline)
                  Text(string(verification, "endpoint")).font(.caption.monospaced()).foregroundStyle(.secondary)
                  Text((string(result, "scope") == "core-read-tool" ? "Core read-only profile · " : "Model endpoint only · ") + string(verification, "status")).font(.caption)
                  if let timestamp = result["checked_at"] as? Double { Text(Date(timeIntervalSince1970: timestamp), style: .date).font(.caption2).foregroundStyle(.secondary) }
                }
                Spacer(); Button("Evidence") { output = string(row, "id") }
              }.padding(12).brandSurface()
            }
          }
          Text("Registered runtimes · \((report["backends"] as? [[String: Any]] ?? []).count)").font(.headline)
          LazyVGrid(columns: [GridItem(.adaptive(minimum: 300), spacing: 12)], spacing: 12) {
            ForEach(rows, id: \.projectRowID) { row in
              VStack(alignment: .leading, spacing: 8) {
                HStack {
                  Text(string(row, "display_name")).font(.headline)
                  Spacer(); Pill(title: string(row, "availability", "unknown"))
                }
                Text(string(row, "local_route")).font(.caption)
                if row["auto_route"] as? Bool == true {
                  Text("Ollama · LM Studio · MLX · llama.cpp").font(.caption).foregroundStyle(.secondary)
                }
                Text(string(row, "verification")).font(.caption).foregroundStyle(.secondary)
                if !string(row, "install_hint").isEmpty {
                  Text(string(row, "install_hint")).font(.caption.monospaced()).textSelection(.enabled)
                }
              }.padding(14).frame(maxWidth: .infinity, alignment: .leading).brandSurface()
            }
          }
        }
      }
      if !failure.isEmpty { Text(failure).foregroundStyle(.orange) }
      HStack {
        Button("Agent runtimes…") { dismiss(); app.openConnections("runtimes") }.buttonStyle(BrandButtonStyle())
        Spacer(); Button("Refresh") { Task { await refresh() } }.buttonStyle(BrandButtonStyle())
        Button("Done") { closed = true; dismiss() }.buttonStyle(BrandButtonStyle()).keyboardShortcut(.cancelAction)
      }
    }.padding(24).frame(width: 920, height: 680)
      .task { await refresh() }.onDisappear { closed = true }
      .centeredDialog(isPresented: Binding(get: { output != nil }, set: { if !$0 { output = nil } }), title: "Readiness evidence") {
        if let output { LocalModelOperationView(job: output).environmentObject(app) }
      }
  }
  private func refresh() async {
    do {
      let value = try await app.engine.call("local.models.compatibility", project.isEmpty ? [:] : ["project": project]) as? [String: Any] ?? [:]
      guard !closed, !Task.isCancelled else { return }; report = value; failure = ""
    } catch { failure = error.localizedDescription }
  }
}
