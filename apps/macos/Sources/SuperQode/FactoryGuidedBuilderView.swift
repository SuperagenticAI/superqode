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
  var onCommit: (() -> Void)? = nil
  let onTrial: () -> Void
  let onDemo: () -> Void
  var inspectAutomatically = true
  @State private var userSelectedStep = false
  @State private var awaitingConnectionPick = false

  private var execution: [[String: Any]] { studio.modelSetup.execution }
  private var primaryExecutionModel: String { execution.first.map { string($0, "reference") } ?? "" }
  private var modelsConfigured: Bool { !execution.isEmpty && execution.allSatisfy { $0["eligible"] as? Bool == true } }
  private var connected: Bool { !app.provider.isEmpty && app.provider != "acp" && app.provider != "agent" && !app.model.isEmpty }
  private var connectedRef: String { connected ? app.provider + "/" + app.model : "" }
  private var setupSuggestionID: String {
    studio.project + ":" + String(setup.saved) + ":" + String(setup.trialPrepared) + ":" + String(setup.hasCompletedRun)
  }
  private var inspectionID: String {
    studio.project + "\n" + String(studio.version) + "\n" + studio.modelSetup.draftingReference + "\n" + String(studio.modelSetup.allowCloud) + "\n"
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
        userSelectedStep = true
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
          Button {
            userSelectedStep = true
            step = FactoryJourneyStep(rawValue: step.rawValue - 1) ?? .intent
          } label: {
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
        if !userSelectedStep, step == .intent {
          step = .suggested(saved: setup.saved, trialPrepared: setup.trialPrepared, verified: setup.hasCompletedRun)
        }
        if inspectAutomatically, studio.modelSetup.draftingReference.isEmpty, connected {
          studio.modelSetup.useConnected(provider: app.provider, model: app.model, harness: app.harness)
        }
      }
      .onChange(of: step) { _, nextStep in
        if nextStep == .models, inspectAutomatically, studio.modelSetup.draftingReference.isEmpty, connected {
          studio.modelSetup.useConnected(provider: app.provider, model: app.model, harness: app.harness)
        }
      }
      .onChange(of: setupSuggestionID) { _, _ in
        if !userSelectedStep, step == .intent {
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
        userSelectedStep = false
        awaitingConnectionPick = false
        step = .intent
      }
      .onChange(of: connectedRef) { _, ref in
        guard awaitingConnectionPick, !ref.isEmpty else { return }
        awaitingConnectionPick = false
        bindModelToFactory(provider: app.provider, model: app.model, harness: app.harness)
      }
      .onChange(of: app.showConnection) { wasShowing, isShowing in
        guard wasShowing && !isShowing && awaitingConnectionPick else { return }
        awaitingConnectionPick = false
        if connected {
          bindModelToFactory(provider: app.provider, model: app.model, harness: app.harness)
        }
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
        Button("Choose model →") { step = .models }
          .buttonStyle(BrandButtonStyle())
          .disabled(!idle || studio.description.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
          .accessibilityIdentifier("factory.journey.continue")
        Button("Use Fix and verify") { onStarter("fix-and-verify") }.disabled(!idle)
        Button("Use Triage, spec & build") { onStarter("triage-spec-build") }.disabled(!idle)
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
      title("Connect your cloud model.", "Pick Grok 4.7 directly, connect a cloud API key like Gemini 4 Neon, or optionally use a local model.")
      ViewThatFits(in: .horizontal) {
        HStack(spacing: 10) { connectionCards }
        VStack(spacing: 10) { connectionCards }
      }
      if app.isManaged {
        Label("Factory stages run direct cloud models (Grok CLI, Gemini/Claude/OpenAI/xAI API keys, or local models), not external CLI agents like Codex or Claude Code.", systemImage: "info.circle")
          .font(.caption).foregroundStyle(.orange)
      }
      if connected, studio.modelSetup.draftingReference != connectedRef {
        Button {
          bindModelToFactory(provider: app.provider, model: app.model, harness: app.harness)
        } label: { Label("Use " + connectedRef, systemImage: "sparkles") }
          .disabled(!idle).accessibilityIdentifier("factory.journey.useConnected")
      }
      HStack {
        Image(systemName: studio.modelSetup.draftingReference.isEmpty ? "bolt.slash" : "cpu")
        Text(studio.modelSetup.draftingReference.isEmpty ? "No model selected yet · pick Grok 4.7 or a Cloud API key above" : studio.modelSetup.draftingReference)
          .font(.callout).textSelection(.enabled)
        Spacer()
        if !studio.modelSetup.draftingReference.isEmpty {
          Button("Check") {
            Task { await studio.modelSetup.inspect(engine: app.engine, yaml: studio.text, checkConnections: true) }
          }.disabled(!idle)
          Button("Clear") { studio.modelSetup.draftingReference = "" }.disabled(!idle)
        }
      }.padding(10).background(Brand.purple.opacity(0.06), in: RoundedRectangle(cornerRadius: 12))
      if studio.modelSetup.isPrivacyBlocked {
        HStack(spacing: 10) {
          Label("This saved draft uses a private local-only route. Switch it to best to use cloud models.", systemImage: "cloud")
            .font(.caption).foregroundStyle(.secondary)
          Spacer(minLength: 8)
          Button("Switch to cloud (best)") {
            studio.modelSetup.allowCloud = true
            let identity = studio.project; let source = studio.version
            Task {
              if !studio.text.isEmpty, studio.project == identity, studio.version == source {
                await studio.edit(engine: app.engine, controls: ["default_route": "best"])
              }
              await studio.modelSetup.inspect(engine: app.engine, yaml: studio.text)
            }
          }.controlSize(.small).disabled(!idle)
            .accessibilityIdentifier("factory.journey.allowCloud")
        }.padding(10).background(Brand.orange.opacity(0.08), in: RoundedRectangle(cornerRadius: 12))
      } else if studio.modelSetup.draftingBlocked {
        Text(string(studio.modelSetup.drafting, "message")).font(.caption).foregroundStyle(.orange)
        Button("Open API key setup") {
          awaitingConnectionPick = true
          app.openConnections("source:key", returningTo: "Factory Studio")
        }.disabled(!idle)
      }
      Button { onBuild() } label: {
        Label(studio.modelSetup.draftingReference.isEmpty ? "Build draft from repo" : "Build my Factory with " + studio.modelSetup.draftingReference, systemImage: "sparkles")
      }
        .buttonStyle(BrandButtonStyle()).disabled(!idle)
        .accessibilityIdentifier("factory.journey.build")
      Text(studio.modelSetup.draftingReference.isEmpty
        ? "Pick Grok 4.7 or connect a Cloud API key above so your Factory does not fall back to a local Ollama model."
        : "Builds a reviewable Factory using " + studio.modelSetup.draftingReference + " on the cloud best route.")
        .font(.caption).foregroundStyle(.secondary)
    }
  }
  @ViewBuilder private var connectionCards: some View {
    Button {
      bindModelToFactory(provider: "grok-cli", model: "grok-4.7", harness: "core")
    } label: {
      VStack(alignment: .leading, spacing: 8) {
        Image(systemName: "bolt.fill").font(.title2).foregroundStyle(Brand.purple)
        Text("Grok 4.7 (Grok CLI)").font(.headline)
        Text("1-click using your Grok CLI login.").font(.caption).foregroundStyle(.secondary)
      }.frame(maxWidth: .infinity, minHeight: 66, alignment: .leading).padding(14)
    }.buttonStyle(ConnectionChoiceStyle(selected: studio.modelSetup.draftingReference == "grok-cli/grok-4.7")).disabled(!idle)
      .accessibilityIdentifier("factory.journey.grokCLI")
    connection("Cloud API key", detail: "Gemini 4 Neon, xAI, Claude, OpenAI.", symbol: "cloud", source: "source:key")
    connection("Local model (optional)", detail: "Ollama or LM Studio on this Mac.", symbol: "desktopcomputer", source: "source:local")
  }
  private func bindModelToFactory(provider: String, model: String, harness: String) {
    studio.modelSetup.allowCloud = true
    studio.modelSetup.useConnected(provider: provider, model: model, harness: harness)
    let reference = provider + "/" + model
    guard !studio.text.isEmpty else { return }
    let identity = studio.project; let source = studio.version
    Task {
      guard studio.project == identity, studio.version == source else { return }
      await studio.edit(engine: app.engine, controls: ["default_route": "best", "binding": "coder", "model": reference])
      if studio.project == identity {
        await studio.validate(engine: app.engine)
        await studio.modelSetup.inspect(engine: app.engine, yaml: studio.text)
      }
    }
  }
  private var review: some View {
    return VStack(alignment: .leading, spacing: 12) {
      title("Make it yours. Then save.", "Check the workflow, models and protected expectations before any agent runs.")
      if primaryExecutionModel == "ollama/qwen3-coder" {
        HStack(spacing: 10) {
          Label("Execution model is still ollama/qwen3-coder.", systemImage: "exclamationmark.triangle.fill")
            .font(.caption).foregroundStyle(.orange)
          Spacer(minLength: 8)
          Button("Use Grok 4.7") { bindModelToFactory(provider: "grok-cli", model: "grok-4.7", harness: "core") }
            .controlSize(.small).disabled(!idle)
          Button("Connect API key") { awaitingConnectionPick = true; app.openConnections("source:key", returningTo: "Factory Studio") }
            .controlSize(.small).disabled(!idle)
        }.padding(10).background(Brand.orange.opacity(0.08), in: RoundedRectangle(cornerRadius: 12))
      }
      LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], spacing: 10) {
        reviewTile("Workflow", value: studio.review.isEmpty ? "Check to preview" : "\((studio.review["stages"] as? [[String: Any]] ?? []).count) stages", symbol: "point.3.connected.trianglepath.dotted", destination: "Workflow")
        reviewTile("Execution models", value: !primaryExecutionModel.isEmpty ? primaryExecutionModel : "Choose models", symbol: "cpu", destination: "Configuration")
        reviewTile("Acceptance", value: setup.hasProtectedChecks ? "Protected checks configured" : "Add protected checks", symbol: "lock.shield", destination: "Acceptance")
        reviewTile("Source & definition", value: setup.saved ? "Revision saved" : "Review your draft", symbol: "doc.text", destination: "Definition")
      }
      HStack(spacing: 12) {
        if !setup.saved {
          Button(setup.validated ? "Save Factory →" : "Check & save Factory →") { onSave() }
            .buttonStyle(BrandButtonStyle()).disabled(!idle || studio.text.isEmpty)
        } else {
          Button("Continue to a trial →") { step = .trial }.buttonStyle(BrandButtonStyle()).disabled(!idle)
        }
        if !setup.validated && !studio.text.isEmpty {
          Button("Validate only") { onValidate() }.disabled(!idle)
        }
        Label(setup.validated ? "Definition checked" : "Validation makes no model calls", systemImage: setup.validated ? "checkmark.circle" : "bolt.slash")
          .font(.caption).foregroundStyle(.secondary)
      }
    }
  }
  private var trial: some View {
    VStack(alignment: .leading, spacing: 12) {
      title("Run your Factory on a real task.", "Write a prompt to prepare a pinned trial and run your agents in an isolated worktree.")
      if !setup.saved {
        VStack(alignment: .leading, spacing: 12) {
          Label("Save your Factory draft first so the trial pins its configuration.", systemImage: "doc.badge.plus").font(.callout)
          HStack(spacing: 10) {
            Button("Save Factory") { onSave() }.buttonStyle(BrandButtonStyle()).disabled(!idle || studio.text.isEmpty)
            Button("Inspect YAML") { studio.navigation.select("Definition") }.disabled(!idle)
          }
        }.padding(16).frame(maxWidth: .infinity, alignment: .leading).background(Brand.purple.opacity(0.06), in: RoundedRectangle(cornerRadius: 16))
      } else if !setup.committed {
        VStack(alignment: .leading, spacing: 12) {
          Label("Commit your new Factory files locally so isolated worktrees start from a clean Git baseline.", systemImage: "arrow.triangle.branch").font(.callout)
          HStack(spacing: 10) {
            if let onCommit {
              Button("Commit Factory files") { onCommit() }.buttonStyle(BrandButtonStyle()).disabled(!idle)
                .accessibilityIdentifier("factory.journey.commit")
            }
            Button("Review in Source control") { studio.navigation.select("Sources") }.disabled(!idle)
          }
        }.padding(16).frame(maxWidth: .infinity, alignment: .leading).background(Brand.purple.opacity(0.06), in: RoundedRectangle(cornerRadius: 16))
      } else if setup.trialPrepared {
        setupAction("Your trial is prepared. Run its ready stages and review any human gates.", button: "Open the active trial", destination: "Runs")
      } else {
        if !primaryExecutionModel.isEmpty {
          HStack(spacing: 8) {
            Label("Execution model: " + primaryExecutionModel, systemImage: primaryExecutionModel.hasPrefix("ollama/") ? "exclamationmark.triangle.fill" : "cpu")
              .font(.caption.weight(.medium))
              .foregroundStyle(primaryExecutionModel == "ollama/qwen3-coder" ? Color.orange : Color.secondary)
            Spacer()
            if primaryExecutionModel == "ollama/qwen3-coder" {
              Button("Switch to Grok 4.7") { bindModelToFactory(provider: "grok-cli", model: "grok-4.7", harness: "core") }
                .controlSize(.small).disabled(!idle)
            }
          }
        }
        TextField("What should this trial accomplish?", text: $trialGoal, axis: .vertical)
          .lineLimit(2...3).textFieldStyle(.roundedBorder)
        if !string(studio.gettingStarted, "demo_goal").isEmpty {
          Button("Use the sample repair task") { trialGoal = string(studio.gettingStarted, "demo_goal") }
        }
        HStack(spacing: 12) {
          Button("Prepare & open trial →") { onTrial() }.buttonStyle(BrandButtonStyle())
            .disabled(!idle || trialGoal.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
          if !setup.hasProtectedChecks {
            Button("Optional: add SuperGauge probes") { studio.navigation.select("Acceptance") }
              .buttonStyle(.link).font(.caption).disabled(!idle)
          }
        }
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
    case .review: setup.saved && setup.committed
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
    Button {
      awaitingConnectionPick = true
      app.openConnections(source, returningTo: "Factory Studio")
    } label: {
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
