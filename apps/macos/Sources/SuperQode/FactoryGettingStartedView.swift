import SwiftUI

struct FactoryGettingStartedView: View {
  @EnvironmentObject private var app: Workspace
  @ObservedObject var studio: FactoryStudioLibrary
  var idle: Bool
  @State private var expanded = false
  @State private var confirmChecks = false
  @State private var reviewedProject = ""
  @State private var reviewedVersion = 0
  @State private var pendingAction = ""
  private var next: [String: Any] { studio.gettingStarted["next_step"] as? [String: Any] ?? [:] }
  private var steps: [[String: Any]] { studio.gettingStarted["steps"] as? [[String: Any]] ?? [] }
  private var checklistIdentity: String {
    studio.project + "\n" + String(studio.text.hashValue) + "\n" + studio.modelSetup.draftingReference + "\n"
      + studio.runs.map { string($0, "id") + string($0, "status") + String($0["verification_valid"] as? Bool ?? false) }.joined(separator: "\n")
  }

  var body: some View {
    VStack(alignment: .leading, spacing: 10) {
      HStack {
        Label("Your first verified run", systemImage: "checklist").font(.headline)
        Spacer()
        Button(studio.setupChecking ? "Checking…" : "Check setup") {
          Task { await studio.inspectGettingStarted(engine: app.engine, checkConnections: true) }
        }.disabled(!idle || studio.setupChecking)
          .accessibilityIdentifier("factory.onboarding.check")
      }
      if !next.isEmpty {
        Text(string(next, "title")).font(.subheadline.bold())
        Text(string(next, "detail")).font(.caption).foregroundStyle(.secondary)
        Button("Open " + string(next, "destination")) {
          studio.navigation.select(string(next, "destination"))
        }.disabled(!idle)
      }
      ForEach(studio.gettingStarted["actions"] as? [[String: Any]] ?? [], id: \.onboardingStepID) { action in
        VStack(alignment: .leading, spacing: 4) {
          Text(string(action, "detail")).font(.caption).foregroundStyle(.orange)
          Button(string(action, "connection").isEmpty ? "Review " + string(action, "destination") : "Open connection setup") {
            if string(action, "connection").isEmpty { studio.navigation.select(string(action, "destination")) }
            else { app.openConnections(string(action, "connection"), returningTo: "Factory Studio") }
          }.disabled(!idle)
        }
      }
      if studio.gettingStarted["demo"] as? Bool == true {
        Button("Run sample probes…") { request("demo.check") }.disabled(!idle || studio.onboardingWorking)
        Text("Sample task: Fix total(values) in app.py so it adds every number, including negatives and empty lists.")
          .font(.caption).textSelection(.enabled)
        if !studio.demoCheck.isEmpty {
          Text(string(studio.demoCheck, "status") == "failed" ? "Defect reproduced. Review the expectations, select an execution model and prepare a repair trial." : "Probe diagnostic: " + string(studio.demoCheck, "status"))
            .font(.caption)
          Text("This diagnostic makes no model calls and grants no SuperGauge or release approval.").font(.caption).foregroundStyle(.secondary)
        }
      } else {
        FactoryDemoStartView()
      }
      HStack {
        Button("Keep draft for next time…") { request("onboarding.draft.save") }
          .disabled(!idle || studio.onboardingWorking || studio.text.isEmpty)
        if studio.gettingStarted["draft_available"] as? Bool == true {
          Button("Restore local draft…") { request("onboarding.draft.load") }
            .disabled(!idle || studio.onboardingWorking)
        }
      }
      DisclosureGroup("First-run checklist", isExpanded: $expanded) {
        ForEach(steps, id: \.onboardingStepID) { row in
          VStack(alignment: .leading, spacing: 3) {
            Text(string(row, "title") + " · " + string(row, "status")).font(.caption.bold())
            Text(string(row, "detail")).font(.caption).foregroundStyle(.secondary)
          }.padding(.vertical, 3)
        }
        Button("Run isolation and application checks…") {
          reviewedProject = studio.project; reviewedVersion = studio.version
          confirmChecks = true
        }.disabled(!idle || studio.review.isEmpty || string(studio.review, "digest") != studio.expectedFileDigest)
        Text("Checks run only after confirmation. Models, protected expectations and release approval remain separate decisions.")
          .font(.caption).foregroundStyle(.secondary)
      }
    }.padding(14).brandSurface()
      .accessibilityIdentifier("factory.onboarding.guide")
      .task(id: checklistIdentity) {
        try? await Task.sleep(for: .milliseconds(250))
        guard !Task.isCancelled else { return }
        await studio.inspectGettingStarted(engine: app.engine)
      }
      .onChange(of: studio.project) { _, _ in confirmChecks = false; pendingAction = "" }
      .onChange(of: studio.text) { _, _ in confirmChecks = false; pendingAction = "" }
      .confirmationDialog("Continue with this setup action?", isPresented: Binding(get: { !pendingAction.isEmpty }, set: { if !$0 { pendingAction = "" } }), titleVisibility: .visible) {
        Button("Continue") {
          let action = pendingAction
          guard !action.isEmpty, idle, studio.project == reviewedProject, studio.version == reviewedVersion else { return }
          pendingAction = ""
          Task { await studio.onboardingAction(engine: app.engine, action: action) }
        }
        Button("Cancel", role: .cancel) { pendingAction = "" }
      } message: {
        Text(pendingAction == "demo.check" ? "Run the sample's three built-in expectations under OS isolation. No models are called. The faulty app should fail; use a real trial for repair and SuperGauge verification."
          : pendingAction == "onboarding.draft.load" ? "Replace the editor's current contents with your local draft. The saved Factory stays unchanged; review and validate the restored draft."
          : "Keep this valid Factory draft in the project's local runtime folder for your next session. This replaces the previous local draft and leaves the saved Factory unchanged. Credentials belong in Connections.")
      }
      .confirmationDialog("Run the saved Factory's application checks?", isPresented: $confirmChecks, titleVisibility: .visible) {
        Button("Run reviewed checks") {
          guard idle, studio.project == reviewedProject, studio.version == reviewedVersion else { return }
          let ticket = studio.navigation.ticket()
          Task {
            await studio.operations.perform(app.engine, "check", ["application": true])
            if studio.project == reviewedProject, studio.version == reviewedVersion {
              studio.navigation.follow(ticket, to: "Operations")
            }
          }
        }
        Button("Cancel", role: .cancel) {}
      } message: {
        Text("Run protected host probes and the build, start, service and health commands declared in the saved Factory. Project commands run in a temporary checkout and can consume resources or contact services. Review them in the definition first. Results open in Operations; this grants no release approval.")
      }
  }
  private func request(_ action: String) {
    reviewedProject = studio.project; reviewedVersion = studio.version; pendingAction = action
  }
}

private extension Dictionary where Key == String, Value == Any {
  var onboardingStepID: String { self["id"] as? String ?? "" }
}
