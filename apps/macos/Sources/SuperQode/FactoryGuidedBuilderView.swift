import SwiftUI

/// A focused front door over the existing Factory engine and source editor.
struct FactoryGuidedBuilderView: View {
  @EnvironmentObject private var app: Workspace
  @Environment(\.accessibilityReduceMotion) private var reduceMotion
  @ObservedObject var studio: FactoryStudioLibrary
  @Binding var step: FactoryJourneyStep
  @Binding var trialGoal: String
  let setup: FactorySetupState
  let idle: Bool
  let onBuild: () -> Void
  let onStarter: (String) -> Void
  let onValidate: () -> Void
  let onSave: () -> Void
  let onTrial: () -> Void
  let onDemo: () -> Void
  var inspectAutomatically = true

  private var execution: [[String: Any]] { studio.modelSetup.execution }
  private var modelsConfigured: Bool { !execution.isEmpty && execution.allSatisfy { $0["eligible"] as? Bool == true } }
  private var connected: Bool { !app.provider.isEmpty && app.provider != "acp" && !app.model.isEmpty }
  private var inspectionID: String {
    studio.project + "\n" + String(studio.version) + "\n" + studio.modelSetup.draftingReference + "\n"
      + studio.runs.map { string($0, "id") + string($0, "status") + String($0["verification_valid"] as? Bool ?? false) }.joined(separator: "\n")
  }

  var body: some View {
    VStack(alignment: .leading, spacing: 16) {
      HStack(alignment: .top) {
        VStack(alignment: .leading, spacing: 6) {
          if step == .intent {
            Text("Build your Factory, one step at a time.").font(.title2.bold())
            Text("Describe the outcome. Review what runs. Keep the evidence.")
              .font(.callout).foregroundStyle(.secondary)
          } else {
            Text("Your Factory").font(.headline)
            Text(studio.description.isEmpty ? "Configure a small, verifiable workflow." : studio.description)
              .font(.caption).foregroundStyle(.secondary).lineLimit(1)
          }
        }
        Spacer(minLength: 12)
        Button { onDemo() } label: { Label("Watch a demo", systemImage: "play.rectangle") }
          .accessibilityIdentifier("factory.journey.demo")
      }
      FactoryFlowMap(nodes: FactoryJourneyStep.allCases.map {
        FactoryFlowNode(id: $0.rawValue, title: $0.title, symbol: $0.symbol, completed: completed($0))
      }, selection: step.rawValue, working: studio.busy || studio.setupChecking || studio.modelSetup.checking, enabled: idle, onSelect: { index in
        guard idle, let target = FactoryJourneyStep(rawValue: index) else { return }
        step = target
      })
      HStack(spacing: 6) {
        Text("STEP \(step.rawValue + 1) OF 5").font(.caption2.weight(.bold)).tracking(1.2)
        Spacer()
        if studio.busy || studio.setupChecking || studio.modelSetup.checking {
          ProgressView().controlSize(.small)
          Text(studio.busy ? "Preparing your draft…" : "Checking setup…").font(.caption)
        }
      }.foregroundStyle(.secondary)
      Group {
        switch step {
        case .intent: intent
        case .models: models
        case .review: review
        case .trial: trial
        case .evidence: evidence
        }
      }.id(step)
        .transition(reduceMotion ? .identity : .opacity.combined(with: .move(edge: .trailing)))
      HStack {
        if step != .intent {
          Button { step = FactoryJourneyStep(rawValue: step.rawValue - 1) ?? .intent } label: {
            Label("Back", systemImage: "chevron.left")
          }.disabled(!idle)
        }
        Spacer()
        Text("Your Factory stays editable as code.").font(.caption).foregroundStyle(.secondary)
      }
    }.padding(20).brandSurface()
      .animation(reduceMotion ? nil : .spring(response: 0.38, dampingFraction: 0.88), value: step)
      .accessibilityIdentifier("factory.journey")
      .onAppear {
        if step == .intent {
          step = .suggested(saved: setup.saved, trialPrepared: setup.trialPrepared, verified: setup.hasCompletedRun)
        }
      }
      .task(id: inspectionID) {
        guard inspectAutomatically else { return }
        do { try await Task.sleep(for: .milliseconds(300)) } catch { return }
        guard !Task.isCancelled, !studio.project.isEmpty else { return }
        await studio.modelSetup.inspect(engine: app.engine, yaml: studio.text)
        guard !Task.isCancelled else { return }
        await studio.inspectGettingStarted(engine: app.engine)
      }
      .onChange(of: studio.project) { _, _ in
        step = .intent
      }
      .onChange(of: setup.saved) { _, saved in
        if saved, step == .review { step = .trial }
      }
      .onChange(of: setup.hasCompletedRun) { _, verified in
        if verified, step == .trial { step = .evidence }
      }
  }

  private var intent: some View {
    VStack(alignment: .leading, spacing: 12) {
      title("What would you like to build?", "Start with an outcome. You can refine every stage later.")
      TextField("For example: fix incoming bugs and verify every change", text: $studio.description, axis: .vertical)
        .lineLimit(2...4).textFieldStyle(.roundedBorder).font(.title3)
        .accessibilityIdentifier("factory.journey.intent")
      ViewThatFits(in: .horizontal) {
        HStack { intentSuggestions }
        VStack(alignment: .leading) { intentSuggestions }
      }
      HStack(spacing: 12) {
        Button("Choose how to build →") { step = .models }
          .buttonStyle(BrandButtonStyle())
          .disabled(!idle || studio.description.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
          .accessibilityIdentifier("factory.journey.continue")
        Button("Use Fix and verify") { onStarter("fix-and-verify") }.disabled(!idle)
      }
    }
  }
  @ViewBuilder private var intentSuggestions: some View {
    ForEach(["Fix bugs and verify the repair", "Triage, specify and build features", "Deliver small improvements continuously"], id: \.self) { value in
      Button(value) { studio.description = value }.controlSize(.small).disabled(!idle)
    }
  }
  private var models: some View {
    VStack(alignment: .leading, spacing: 12) {
      title("Choose your starting point.", "A model can help draft the Factory. Its stages keep their own execution bindings.")
      HStack(spacing: 12) {
        connection("Local model", detail: "Use a model on your machine.", symbol: "desktopcomputer", source: "source:local")
        connection("Frontier model", detail: "Use your own API key.", symbol: "cloud", source: "source:key")
      }
      if connected {
        Button {
          studio.modelSetup.useConnected(provider: app.provider, model: app.model, harness: app.harness)
        } label: { Label("Draft with " + app.provider + "/" + app.model, systemImage: "sparkles") }
          .disabled(!idle).accessibilityIdentifier("factory.journey.useConnected")
      }
      HStack {
        Image(systemName: studio.modelSetup.draftingReference.isEmpty ? "bolt.slash" : "cpu")
        Text(studio.modelSetup.draftingReference.isEmpty ? "Repository inspection · no drafting-model call" : studio.modelSetup.draftingReference)
          .font(.callout).textSelection(.enabled)
        Spacer()
        if !studio.modelSetup.draftingReference.isEmpty {
          Button("Check") {
            Task { await studio.modelSetup.inspect(engine: app.engine, yaml: studio.text, checkConnections: true) }
          }.disabled(!idle)
          Button("Clear") { studio.modelSetup.draftingReference = "" }.disabled(!idle)
        }
      }.padding(10).background(Brand.purple.opacity(0.06), in: RoundedRectangle(cornerRadius: 12))
      if studio.modelSetup.draftingBlocked {
        Text(string(studio.modelSetup.drafting, "message")).font(.caption).foregroundStyle(.orange)
        Button("Review model permissions") { studio.navigation.select("Configuration") }
      }
      Button("Inspect repository & build a draft…") { onBuild() }
        .buttonStyle(BrandButtonStyle()).disabled(!idle)
        .accessibilityIdentifier("factory.journey.build")
      Text("You review the proposal before saving. Connecting a provider alone never permits cloud use.")
        .font(.caption).foregroundStyle(.secondary)
    }
  }
  private var review: some View {
    VStack(alignment: .leading, spacing: 12) {
      title("Make it yours. Then save.", "Check the workflow, models and protected expectations before any agent runs.")
      LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 10) {
        reviewTile("Workflow", value: studio.review.isEmpty ? "Check to preview" : "\((studio.review["stages"] as? [[String: Any]] ?? []).count) stages", symbol: "point.3.connected.trianglepath.dotted", destination: "Workflow")
        reviewTile("Execution models", value: modelsConfigured ? "Bindings configured" : "Choose models", symbol: "cpu", destination: "Configuration")
        reviewTile("Acceptance", value: setup.hasProtectedChecks ? "Protected checks configured" : "Add protected checks", symbol: "lock.shield", destination: "Acceptance")
        reviewTile("Source & definition", value: setup.saved ? "Revision saved" : "Review your draft", symbol: "doc.text", destination: "Definition")
      }
      HStack(spacing: 12) {
        if !setup.validated {
          Button("Check my Factory") { onValidate() }.buttonStyle(BrandButtonStyle()).disabled(!idle || studio.text.isEmpty)
        } else if !setup.saved {
          Button("Review & save…") { onSave() }.buttonStyle(BrandButtonStyle()).disabled(!idle)
        } else {
          Button("Continue to a trial →") { step = .trial }.buttonStyle(BrandButtonStyle()).disabled(!idle)
        }
        Label(setup.validated ? "Definition checked" : "Validation makes no model calls", systemImage: setup.validated ? "checkmark.circle" : "bolt.slash")
          .font(.caption).foregroundStyle(.secondary)
      }
    }
  }
  private var trial: some View {
    VStack(alignment: .leading, spacing: 12) {
      title("Try one small, real task.", "A trial pins the inputs. Running its worker is a separate, confirmed action.")
      if !setup.saved {
        setupAction("Save the reviewed Factory first.", button: "Review the draft", destination: "Definition")
      } else if !setup.hasProtectedChecks {
        setupAction("Define the finish line with protected acceptance checks.", button: "Set up acceptance", destination: "Acceptance")
      } else if !setup.committed {
        setupAction("Review and commit or isolate Factory source changes.", button: "Review source changes", destination: "Sources")
      } else if setup.trialPrepared {
        setupAction("Your trial is prepared. Run its ready stages and review any human gates.", button: "Open the active trial", destination: "Runs")
      } else {
        TextField("What should this trial accomplish?", text: $trialGoal, axis: .vertical)
          .lineLimit(2...3).textFieldStyle(.roundedBorder)
        if !string(studio.gettingStarted, "demo_goal").isEmpty {
          Button("Use the sample repair task") { trialGoal = string(studio.gettingStarted, "demo_goal") }
        }
        Button("Prepare my trial…") { onTrial() }.buttonStyle(BrandButtonStyle())
          .disabled(!idle || trialGoal.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
      }
      Button("See what a run looks like first") { onDemo() }
        .disabled(!idle)
    }
  }
  private var evidence: some View {
    VStack(alignment: .leading, spacing: 12) {
      Image(systemName: setup.hasCompletedRun ? "checkmark.shield.fill" : "checkmark.shield")
        .font(.system(size: 46)).foregroundStyle(setup.hasCompletedRun ? Color.green : Brand.purple)
      title(setup.hasCompletedRun ? "A verified trial. Evidence you can inspect." : "Verification is the finish line.",
            setup.hasCompletedRun ? "Inspect the changed files, protected checks and reported usage. Production release still needs your approval." : "A completed coding task needs protected verification. Review its evidence and resolve any held checks.")
      HStack {
        Button("Inspect trial & evidence") { studio.navigation.select("Runs") }.buttonStyle(BrandButtonStyle()).disabled(!idle)
        if setup.hasCompletedRun { Button("Compare an improvement") { studio.navigation.select("Improve") }.disabled(!idle) }
      }
    }
  }
  private func completed(_ item: FactoryJourneyStep) -> Bool {
    switch item {
    case .intent: setup.saved || (setup.hasDraft && !studio.description.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
    case .models: setup.hasCompletedRun || (modelsConfigured && execution.allSatisfy { string($0, "state") != "unchecked" })
    case .review: setup.saved && setup.hasProtectedChecks && setup.committed
    case .trial: setup.trialPrepared
    case .evidence: setup.hasCompletedRun
    }
  }
  private func title(_ headline: String, _ detail: String) -> some View {
    VStack(alignment: .leading, spacing: 7) {
      Text(headline).font(.title2.bold())
      Text(detail).font(.callout).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
    }
  }
  private func connection(_ title: String, detail: String, symbol: String, source: String) -> some View {
    Button { app.openConnections(source, returningTo: "Factory Studio") } label: {
      VStack(alignment: .leading, spacing: 8) {
        Image(systemName: symbol).font(.title2).foregroundStyle(Brand.purple)
        Text(title).font(.headline)
        Text(detail).font(.caption).foregroundStyle(.secondary)
      }.frame(maxWidth: .infinity, minHeight: 66, alignment: .leading).padding(14)
    }.buttonStyle(ConnectionChoiceStyle(selected: false)).disabled(!idle)
  }
  private func reviewTile(_ title: String, value: String, symbol: String, destination: String) -> some View {
    Button { studio.navigation.select(destination) } label: {
      HStack(alignment: .top, spacing: 10) {
        Image(systemName: symbol).foregroundStyle(Brand.purple)
        VStack(alignment: .leading, spacing: 5) {
          Text(title).font(.subheadline.bold())
          Text(value).font(.caption).foregroundStyle(.secondary)
        }
        Spacer(minLength: 0)
        Image(systemName: "chevron.right").font(.caption2).foregroundStyle(.secondary)
      }.padding(16).frame(maxWidth: .infinity, minHeight: 65, alignment: .leading)
    }.buttonStyle(ConnectionChoiceStyle(selected: false)).disabled(!idle)
  }
  private func setupAction(_ detail: String, button: String, destination: String) -> some View {
    VStack(alignment: .leading, spacing: 14) {
      Label(detail, systemImage: "arrow.turn.down.right").font(.callout)
      Button(button) { studio.navigation.select(destination) }.buttonStyle(BrandButtonStyle()).disabled(!idle)
    }.padding(20).frame(maxWidth: .infinity, alignment: .leading).background(Brand.purple.opacity(0.06), in: RoundedRectangle(cornerRadius: 16))
  }
}
