import SwiftUI

/// Inline guidance follows actual project, connection and run state. It never
/// starts an agent, installs software or changes credentials on the user's behalf.
struct GettingStartedView: View {
  @ObservedObject var draftStore: DraftStore
  @EnvironmentObject var app: Workspace
  @AppStorage("nativeShowStarterGuide") private var showStarterGuide = true
  private var hasRun: Bool {
    app.projectJobs.contains { string($0, "kind") == "task" && string($0, "status") == "completed" }
  }
  private var hasConnection: Bool {
    app.isManaged || (!app.model.isEmpty && app.routeStatus["ready"] as? Bool == true)
  }
  var body: some View {
    ScrollView {
      if !app.project.isEmpty && !((showStarterGuide && !hasRun) || app.starterTourRequested) {
        newThreadStart
      } else {
        guide
      }
    }.defaultScrollAnchor(.top)
  }
  /// The first screen of a new thread: one question, and the connection front and centre.
  private var newThreadStart: some View {
    VStack(spacing: 22) {
      BrandMark().frame(width: 44, height: 44)
      Text("What should we work on?")
        .font(.system(size: 28, weight: .semibold)).multilineTextAlignment(.center)
      if app.connectionDisconnected {
        VStack(spacing: 14) {
          Label("Connect an agent or a model to start", systemImage: "cable.connector")
            .font(.system(size: 15, weight: .semibold))
          Text("Use a coding agent you already have, or your own model through a local runtime or API key.")
            .font(.callout).foregroundStyle(.secondary).multilineTextAlignment(.center)
            .fixedSize(horizontal: false, vertical: true)
          HStack(spacing: 12) {
            Button { app.openConnections("menu:vendors") } label: {
              Label("Agent", systemImage: "person.crop.circle.badge.checkmark")
                .font(.system(size: 14, weight: .semibold)).frame(minWidth: 130, minHeight: 30)
            }.buttonStyle(BrandButtonStyle())
              .help("Connect a coding agent with its existing subscription or sign-in.")
            Button { app.openConnections("menu:harness") } label: {
              Label("Model", systemImage: "cpu")
                .font(.system(size: 14, weight: .semibold)).frame(minWidth: 130, minHeight: 30)
            }.controlSize(.large)
              .help("Use a local model or your API key with a SuperQode harness.")
          }.disabled(app.connectionPickerDisabled)
          if !app.connected {
            Text("Waiting for the local engine…").font(.caption).foregroundStyle(.secondary)
          }
        }
        .padding(24).frame(maxWidth: 520)
        .background(Color.qPanel.opacity(0.6), in: RoundedRectangle(cornerRadius: 14))
        .overlay(RoundedRectangle(cornerRadius: 14).stroke(Color.orange.opacity(0.45), lineWidth: 1))
      } else {
        HStack(spacing: 12) {
          if let identity = app.composerHarnessIdentity { HarnessIcon(identity: identity, size: 30) }
          VStack(alignment: .leading, spacing: 2) {
            Text("Connected").font(.caption).foregroundStyle(.secondary)
            Text(app.connectionDisplayName).font(.system(size: 14, weight: .medium)).lineLimit(1)
          }
          Spacer(minLength: 12)
          Button("Change") { app.openConnections() }.disabled(app.connectionPickerDisabled)
        }
        .padding(14).frame(maxWidth: 520)
        .background(Color.qPanel.opacity(0.6), in: RoundedRectangle(cornerRadius: 12))
        .overlay(RoundedRectangle(cornerRadius: 12).stroke(Color.secondary.opacity(0.25), lineWidth: 1))
        Text("Describe a change below. Review tool requests and inspect the result as your agent works.")
          .font(.callout).foregroundStyle(.secondary).multilineTextAlignment(.center)
      }
      Button("Getting started & learning") { app.showLearningGuide = true }
        .buttonStyle(.link).font(.caption)
    }
    .padding(.horizontal, 28).padding(.top, 56).padding(.bottom, 28)
    .frame(maxWidth: .infinity)
  }
  private var guide: some View {
      VStack(alignment: .leading, spacing: 22) {
        if app.project.isEmpty {
          BrandMark().frame(width: 62, height: 62)
          PageTitle(
            eyebrow: "Welcome to SuperQode", title: "Your first change starts here.",
            subtitle: "Bring your project and the coding agent or model you already use.")
          step(1, "Open your project", "Choose the folder containing your code.", done: false)
          step(
            2, "Connect your agent or model",
            "Use an existing subscription, a local model or your API key.", done: false)
          step(
            3, "Describe a change", "Watch the work, decide on permissions and review the diff.",
            done: false)
          Button("Open project…", action: app.chooseProject).buttonStyle(BrandButtonStyle())
            .disabled(!app.connected).keyboardShortcut("o")
          if !app.connected { ProgressView("Starting the local engine…").font(.caption) }
          Button("Learn harness evaluation & optimization") {
            app.learningTopic = "Harnesses"
            app.showLearningGuide = true
          }
          Text("No SuperQode account required. Requests go to the agent or provider you choose.")
            .font(.caption).foregroundStyle(.secondary)
        } else if (showStarterGuide && !hasRun) || app.starterTourRequested {
          PageTitle(
            eyebrow: "Getting started",
            title: hasConnection ? "Ask for your first change." : "Connect your coding agent.",
            subtitle:
              "Use an existing subscription, a local model or your API key. Advanced setup can wait."
          )
          HStack(spacing: 14) {
            Label("Project opened", systemImage: "checkmark.circle.fill").foregroundStyle(.green)
            Image(systemName: "chevron.right").foregroundStyle(.tertiary)
            Label(
              hasConnection ? "Connection selected" : "Connect your agent",
              systemImage: hasConnection ? "checkmark.circle.fill" : "circle"
            )
            .foregroundStyle(hasConnection ? Color.green : .secondary)
            Image(systemName: "chevron.right").foregroundStyle(.tertiary)
            Text("Describe your change").foregroundStyle(.secondary)
          }.font(.caption)
          if !hasConnection {
            HStack(spacing: 12) {
              Button("Connect an agent…") { app.openConnections("menu:vendors") }
                .buttonStyle(BrandButtonStyle())
              Button("Use a model…") { app.openConnections("menu:harness") }
            }.disabled(app.connectionPickerDisabled)
          }
          Button("Start with a project overview") {
            app.draft =
              "Explain how this project is structured and suggest one small improvement. Do not edit files or run commands."
          }.disabled(!draftStore.text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            .help("Adds a suggested prompt without sending it. Keep or edit it before starting.")
          Button("Start with a harness setup check · no model calls") {
            app.section = "Evaluations"
            app.showWelcome = false
          }
          HStack {
            Button("How it works") { app.showLearningGuide = true }
            Spacer()
            Button("Hide getting started") {
              showStarterGuide = false
              app.starterTourRequested = false
            }.font(.caption)
          }
        }
      }.padding(28).frame(maxWidth: 680, alignment: .leading).frame(
        maxWidth: .infinity, alignment: .leading)
  }
  private func step(_ number: Int, _ title: String, _ detail: String, done: Bool) -> some View {
    HStack(alignment: .top, spacing: 12) {
      ZStack {
        Circle().fill(done ? Color.green.opacity(0.12) : Brand.purple.opacity(0.14))
        if done {
          Image(systemName: "checkmark").foregroundStyle(.green)
        } else {
          Text(String(number)).modifier(BrandText())
        }
      }.font(.system(size: 12, weight: .semibold)).frame(width: 28, height: 28)
      VStack(alignment: .leading, spacing: 4) {
        Text(title).font(.headline)
        Text(detail).font(.callout).foregroundStyle(.secondary).fixedSize(
          horizontal: false, vertical: true)
      }
    }
  }
}

struct LearningGuideView: View {
  @EnvironmentObject var app: Workspace
  @DialogDismiss private var dismiss
  @AppStorage("nativeShowStarterGuide") private var showStarterGuide = true
  var body: some View {
    VStack(alignment: .leading, spacing: 18) {
      HStack {
        Label("Getting started & learning", systemImage: "book.closed").font(.headline)
        Spacer()
        nativeButton("dialog.done", action: { dismiss() }, title: "Done") { Text("Done") }
      }
      Picker("Learn", selection: $app.learningTopic) {
        Text("Start coding").tag("Start coding")
        Text("Review your work").tag("Review your work")
        Text("Harnesses").tag("Harnesses")
        Text("Go further").tag("Go further")
      }.pickerStyle(.segmented)
      ScrollView {
        VStack(alignment: .leading, spacing: 20) {
          if app.learningTopic == "Start coding" {
            lesson(
              "1 · Open a project",
              "Use Open project or ⌘O to select your source folder. Recent projects are in the sidebar. This does not upload your project to SuperQode."
            )
            lesson(
              "2 · Connect what you already use",
              "Choose Connect → Existing harnesses → Subscriptions for your coding agent. The agent handles its account and model. For your own local model or API key, choose a harness with your model instead. Protocols and custom harnesses are optional advanced paths."
            )
            lesson(
              "3 · Ask, approve, review",
              "Describe one concrete change and press Enter to send (Shift-Enter adds a line). Read the streamed output, approve or deny permission requests, and use Stop run if needed. Normal provider or subscription limits apply. Saving credentials does not verify an account."
            )
            HStack {
              Button(app.project.isEmpty ? "Open project…" : "Go to Agent Space") {
                dismiss()
                app.section = "Workspace"
                app.showWelcome = app.project.isEmpty
                if app.project.isEmpty { app.chooseProject() }
              }.buttonStyle(BrandButtonStyle()).disabled(!app.connected)
              Button("Show getting started again") {
                showStarterGuide = true
                app.starterTourRequested = true
                app.showWelcome = app.project.isEmpty
                app.section = "Workspace"
                app.selectJob("")
                dismiss()
              }
            }
          } else if app.learningTopic == "Review your work" {
            lesson(
              "See what changed",
              "Open Files to inspect the diff and edit source. Review before staging or committing. Checkpoints offers guarded recovery for changes recorded by local tasks; inspect its warnings before restoring."
            )
            lesson(
              "Keep the conversation",
              "Select a completed run and use Continue session when its connection supports it. Exact session continuation depends on the agent or server. Otherwise, start a new task deliberately."
            )
            lesson(
              "Use your terminal",
              "Terminal is your interactive project shell. Start it explicitly and keep working there while using the native app. Starting the app does not automatically execute shell commands."
            )
            navigate("Open Files", section: "Files")
          } else if app.learningTopic == "Harnesses" {
            lesson(
              "1 · Inspect a suite without credentials",
              "Open a project, go to Evaluations and choose a built-in harness and bundled suite. Leave Live evaluation off and choose Check setup. This validates configuration, makes no model calls and skips task execution. It does not measure quality."
            )
            lesson(
              "2 · Learn to judge routing examples",
              "In Optimization, open More harness workflows → Tune routing decisions from examples. Choose Try practice examples to label synthetic cases without a file or model calls. Practice data cannot authorize adoption."
            )
            lesson(
              "3 · Measure, improve, review",
              "Connect a supported provider/local model, add your real graded tasks, then explicitly enable live evaluation. Compare baseline and candidates on the same held-out tasks. Set budgets before optimization, inspect regressions and candidate diffs, and adopt only verified evidence."
            )
            if app.project.isEmpty {
              Button("Open project…") {
                dismiss()
                app.chooseProject()
              }.buttonStyle(BrandButtonStyle()).disabled(!app.connected)
            } else {
              navigate("Open Evaluations", section: "Evaluations")
              navigate("Open Optimization", section: "Optimization")
            }
          } else {
            lesson(
              "Find the right harness",
              "Harness Hub lets you inspect supported harnesses and their capabilities. Models shows your local inventory and provider setup. Use Improve & more in the sidebar when you want these tools."
            )
            lesson(
              "Measure before optimizing",
              "Evaluations compares harnesses on tasks and exposes results and regressions. Begin with setup checks. Live evaluations call your configured models and may incur charges."
            )
            lesson(
              "Improve with a budget",
              "Optimization runs bounded experiments and presents a candidate diff for review. Set evaluation and cost budgets before live execution. Tools exposes more engine workflows when you need them."
            )
            navigate("Explore Harness Hub", section: "Harness Hub")
          }
        }.padding(.vertical, 12).frame(maxWidth: .infinity, alignment: .leading)
      }.defaultScrollAnchor(.top).id(app.learningTopic)
    }.padding(24).frame(width: 650, height: 570).background { BrandBackdrop() }
  }
  private func lesson(_ title: String, _ body: String) -> some View {
    VStack(alignment: .leading, spacing: 8) {
      Text(title).font(.headline)
      Text(body).font(.callout).foregroundStyle(.secondary).fixedSize(
        horizontal: false, vertical: true)
    }
  }
  private func navigate(_ title: String, section: String) -> some View {
    Button(title) {
      app.section = section
      app.showWelcome = false
      dismiss()
    }.buttonStyle(BrandButtonStyle())
      .disabled(app.project.isEmpty)
  }
}
