import SwiftUI

/// Inline guidance follows actual project, connection and run state. It never
/// starts an agent, installs software or changes credentials on the user's behalf.
struct GettingStartedView: View {
  @ObservedObject var draftStore: DraftStore
  @EnvironmentObject var app: Workspace
  @AppStorage("nativeShowStarterGuide") private var showStarterGuide = true
  /// Global and permanent: the guide appears once, until a first message is
  /// sent or it is closed. Learning can reopen it.
  @AppStorage(StarterGuide.completedKey) private var starterGuideCompleted = false
  /// Anyone with a recorded run in any project already knows the basics.
  private var hasRun: Bool {
    app.jobs.contains { string($0, "kind") == "task" }
  }
  private var showsGuide: Bool {
    app.starterTourRequested || (!starterGuideCompleted && showStarterGuide && !hasRun)
  }
  private var hasConnection: Bool {
    app.isManaged || (!app.model.isEmpty && app.routeStatus["ready"] as? Bool == true)
  }
  var body: some View {
    ScrollView {
      if !app.project.isEmpty && !showsGuide {
        newThreadStart
      } else {
        guide
      }
    }.defaultScrollAnchor(.top)
    .onAppear { markCompletedForExistingUser() }
    .onChange(of: hasRun) { _, _ in markCompletedForExistingUser() }
  }
  private func markCompletedForExistingUser() {
    if hasRun && !starterGuideCompleted { starterGuideCompleted = true }
  }
  private func closeGuide() {
    starterGuideCompleted = true
    showStarterGuide = false
    app.starterTourRequested = false
  }
  /// The first screen of a new thread: one question, and the connection front and centre.
  private var newThreadStart: some View {
    // Disconnected: the connection grid is the whole task, so keep it compact
    // enough to sit above the composer without scrolling in a normal window.
    let disconnected = app.connectionDisconnected
    return VStack(spacing: disconnected ? 14 : 22) {
      BrandMark().frame(width: disconnected ? 32 : 44, height: disconnected ? 32 : 44)
      Text(disconnected ? "Connect an agent or a model to start" : "What should we work on?")
        .font(.system(size: disconnected ? 22 : 28, weight: .semibold)).multilineTextAlignment(.center)
      if disconnected {
        VStack(spacing: 12) {
          Text("Use a coding agent you already have, or your own model through a local runtime or API key.")
            .font(.callout).foregroundStyle(.secondary).multilineTextAlignment(.center)
            .fixedSize(horizontal: false, vertical: true)
          ConnectionStartGrid()
          if !app.connected {
            Text("Waiting for the local engine…").font(.caption).foregroundStyle(.secondary)
          }
        }
        .padding(16).frame(maxWidth: 860)
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
    .padding(.horizontal, 28).padding(.top, app.connectionDisconnected ? 20 : 56).padding(.bottom, 20)
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
          Button("What Super Agent and DeepSeek Harness do") {
            app.learningTopic = LearningTopics.superAgent
            app.showLearningGuide = true
          }
          Text("No SuperQode account required. Requests go to the agent or provider you choose.")
            .font(.caption).foregroundStyle(.secondary)
        } else if showsGuide {
          HStack {
            Spacer()
            Button(action: closeGuide) {
              Image(systemName: "xmark").font(.system(size: 12, weight: .semibold))
                .frame(width: 24, height: 24)
            }.buttonStyle(.borderless).help("Close getting started. Reopen it from Getting started & learning.")
              .accessibilityLabel("Close getting started")
          }
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
              Button("Connect an agent…") { app.openConnections("menu:root") }
                .buttonStyle(BrandButtonStyle())
              Button("Use a local model…") { app.openConnections("source:local") }
                .buttonStyle(BrandButtonStyle())
            }.disabled(app.connectionPickerDisabled)
            Button("Use an API key or another harness…") { app.openConnections("menu:harness") }
              .disabled(app.connectionPickerDisabled)
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
            Button("Hide getting started", action: closeGuide).font(.caption)
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

/// Plain-language lessons for people who have not used Super Agent or DeepSeek Harness.
enum LearningTopics {
  static let superAgent = "Super Agent"

  struct Lesson: Equatable {
    var title: String
    var detail: String
  }

  static let superAgentLessons: [Lesson] = [
    Lesson(
      title: "Super Agent drafts a harness",
      detail: "Super Agent is a SuperQode preview. You describe a job for this repository, and SuperQode prepares a harness you can read before anything is turned on. It is not a chat, and it does not start coding by itself."
    ),
    Lesson(
      title: "What you do there",
      detail: "Open a project, describe the job, and press Draft Super Agent. Read the five sections. Write why you are saving, then press Save reviewed draft. The harness stays off. Run Monty check only if you want a template printed in a read-only sandbox. Enable saved revision only when a provider and model are already on the draft. Enable opens Agent Space with that harness selected. You still type a request and press Send."
    ),
    Lesson(
      title: "What drafting does not do",
      detail: "Drafting does not call a model, install a plugin, or send a prompt. The Monty check prints a template and is not installed. If Monty is missing, the check is refused and is not run on this Mac. Recursion stays off. Saved files stay in the project under .superqode/creator."
    ),
    Lesson(
      title: "DeepSeek Harness is a different tool",
      detail: "DeepSeek Harness is a coding backend. DeepSeek runs the agent loop, and SuperQode hosts it and shows the reply. On Local AI, choose DeepSeek Harness, install it if that row asks, pick a model that is already installed, then press Start coding. Type in Agent Space and press Send, the same as any other harness. It is not the DeepSeek plugin market. Super Agent does not load DeepSeek plugins."
    ),
    Lesson(
      title: "Use the one you mean",
      detail: "Use Super Agent when you want to review a harness before it is allowed to work. Use DeepSeek Harness when you want DeepSeek to code in the thread. Opening either screen does not install DeepSeek or turn a draft on. The names are easy to mix up. They are not the same feature."
    ),
  ]
}

enum StarterGuide {
  static let completedKey = "nativeStarterGuideCompleted"
  /// Called after the engine accepts a message.
  static func markCompleted(_ defaults: UserDefaults = .standard) {
    if !defaults.bool(forKey: completedKey) { defaults.set(true, forKey: completedKey) }
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
        Text("Super Agent").tag(LearningTopics.superAgent)
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
          } else if app.learningTopic == LearningTopics.superAgent {
            ForEach(Array(LearningTopics.superAgentLessons.enumerated()), id: \.offset) { _, item in
              lesson(item.title, item.detail)
            }
            if app.project.isEmpty {
              Text("Open a project before Super Agent. Local AI is available first if you want to look at DeepSeek Harness.")
                .font(.callout).foregroundStyle(.secondary)
            }
            HStack(spacing: 12) {
              Button("Open Super Agent") {
                app.section = "Super Agent"
                app.showWelcome = false
                dismiss()
              }.buttonStyle(BrandButtonStyle())
                .disabled(app.project.isEmpty)
              Button("Open Local AI") {
                app.section = "Models"
                app.showWelcome = false
                dismiss()
              }.buttonStyle(BrandButtonStyle())
                .help("Choose DeepSeek Harness there when you want that coding backend.")
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
    }.padding(24).frame(width: 760, height: 570).background { BrandBackdrop() }
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
