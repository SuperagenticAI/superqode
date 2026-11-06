import SwiftUI

struct ComposeTaskScreen: View {
  let project: String
  var parent: String? = nil
  @EnvironmentObject private var store: CompanionStore
  @Environment(\.dismiss) private var dismiss
  @State private var selectedProfile = ""
  @State private var prompt = ""
  @State private var mode = "code"
  @State private var submitting = false
  @State private var issue = ""
  @State private var requestKey = UUID().uuidString
  private var profiles: [RemoteRecord] { store.profiles.filter { $0.text("project") == project } }
  private var profile: RemoteRecord? { profiles.first { $0.id == selectedProfile } }

  var body: some View {
    ScrollView {
      VStack(alignment: .leading, spacing: 20) {
        CompanionCard {
          Label(parent == nil ? "A fresh start" : "Continue this conversation", systemImage: "bubble.left.and.bubble.right")
            .font(.headline)
          Text("Choose a connection explicitly. Your Mac keeps the model, credentials and project files.").font(.subheadline).foregroundStyle(.secondary)
          Picker("Connection", selection: $selectedProfile) {
            Text("Choose a connection").tag("")
            ForEach(profiles) { Text($0.text("name")).tag($0.id) }
          }
          if let profile {
            HarnessBadge(name: profile.text("harness"))
            Text(profile.text("permission_note")).font(.caption).foregroundStyle(.secondary)
            if !profile.flag("local_only") { Text("This route may use cloud inference or the agent's own permissions.").font(.caption).foregroundStyle(.orange) }
          }
          Picker("Mode", selection: $mode) {
            Text("Code").tag("code")
            Text("Plan").tag("plan").disabled(profile?.flag("enforces_controls") != true)
            Text("Chat").tag("chat")
          }.pickerStyle(.segmented)
        }
        CompanionCard {
          Text("What would you like to work on?").font(.headline)
          TextEditor(text: $prompt).frame(minHeight: 180).scrollContentBackground(.hidden)
            .accessibilityLabel("Task prompt")
          Text("\(prompt.count) / 32,000 characters").font(.caption).foregroundStyle(.secondary)
        }
        if !issue.isEmpty { Label(issue, systemImage: "exclamationmark.triangle").font(.subheadline).foregroundStyle(.orange) }
        Button { Task { await submit() } } label: {
          HStack { if submitting { ProgressView() }; Label("Run on my Mac", systemImage: "arrow.up") }
            .fontWeight(.semibold).frame(maxWidth: .infinity).padding(.vertical, 10)
        }.buttonStyle(.borderedProminent).foregroundStyle(.black)
          .disabled(submitting || selectedProfile.isEmpty || prompt.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty || prompt.count > 32000)
        Text("Closing this screen does not cancel a submitted job. Inspect Activity before retrying if the connection drops.")
          .font(.caption).foregroundStyle(.secondary)
      }.padding(20)
    }.background(CompanionTheme.background).navigationTitle(parent == nil ? "New thread" : "Continue thread")
      .navigationBarTitleDisplayMode(.inline)
      .toolbar { Button("Close") { dismiss() }.disabled(submitting) }
      .interactiveDismissDisabled(submitting)
      .onChange(of: selectedProfile) { _, _ in if mode == "plan", profile?.flag("enforces_controls") != true { mode = "code" } }
  }
  private func submit() async {
    guard let api = store.api else { return }
    submitting = true; issue = ""
    defer { submitting = false }
    var params: [String: JSONValue] = ["profile": .string(selectedProfile), "prompt": .string(prompt), "interaction_mode": .string(mode)]
    if let parent { params["parent_id"] = .string(parent) }
    do {
      _ = try await api.rpc("tasks.start", params, key: requestKey)
      await store.refreshActivity()
      dismiss()
    } catch { issue = error.localizedDescription }
  }
}
