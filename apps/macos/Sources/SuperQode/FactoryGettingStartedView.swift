import SwiftUI

struct FactoryGettingStartedView: View {
  @EnvironmentObject private var app: Workspace
  @ObservedObject var studio: FactoryStudioLibrary
  var idle: Bool
  @State private var expanded = false
  @State private var confirmChecks = false
  @State private var reviewedProject = ""
  @State private var reviewedVersion = 0
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
          Task { await studio.inspectGettingStarted(engine: app.engine) }
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
      .onChange(of: studio.project) { _, _ in confirmChecks = false }
      .onChange(of: studio.text) { _, _ in confirmChecks = false }
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
}

private extension Dictionary where Key == String, Value == Any {
  var onboardingStepID: String { self["id"] as? String ?? "" }
}
