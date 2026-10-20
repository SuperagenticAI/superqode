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
            Button("Choose connection…") { app.showConnection = true }.buttonStyle(
              BrandButtonStyle())
          }
          Button("Start with a project overview") {
            app.draft =
              "Explain how this project is structured and suggest one small improvement. Do not edit files or run commands."
          }.disabled(!draftStore.text.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            .help("Adds a suggested prompt without sending it. Keep or edit it before starting.")
          HStack {
            Button("How it works") { app.showLearningGuide = true }
            Spacer()
            Button("Hide getting started") {
              showStarterGuide = false
              app.starterTourRequested = false
            }.font(.caption)
          }
        } else {
          PageTitle(
            eyebrow: "Agent Space", title: "What shall we build?",
            subtitle:
              "Describe a change below. Review tool requests and inspect the result as your agent works."
          )
          Button("Getting started & learning") { app.showLearningGuide = true }
        }
      }.padding(28).frame(maxWidth: 680, alignment: .leading).frame(
        maxWidth: .infinity, alignment: .leading)
    }.defaultScrollAnchor(.top)
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
              "Describe one concrete change and press ⌘Return. Read the streamed output, approve or deny permission requests, and use Stop run if needed. Normal provider or subscription limits apply. Saving credentials does not verify an account."
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
