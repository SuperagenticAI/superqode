import AppKit
import SwiftUI

/// The native annotation surface uses the same sealed-round service as the TUI.
struct TuningView: View {
  @EnvironmentObject var app: Workspace
  private let initialExperimentID: String
  @State private var sessions: [[String: Any]] = []
  @State private var current: [String: Any] = [:]
  @State private var selected = ""
  @State private var source = ""
  @State private var pack = "factory_route"
  @State private var reflection = "openai/gpt-4.1-mini"
  @State private var evaluations = 30
  @State private var cost = 2.0
  @State private var batch = 5
  @State private var label = ""
  @State private var rationale = ""
  @State private var failure = ""
  @State private var busy = false
  private var rows: [[String: Any]] { current["review"] as? [[String: Any]] ?? [] }
  private var example: [String: Any] { rows.first ?? [:] }
  private var blocked: Bool { busy || app.busy || app.anyActive }

  init(experimentID: String = "") { initialExperimentID = experimentID }

  var body: some View {
    ScrollView {
      VStack(alignment: .leading, spacing: 18) {
        PageTitle(eyebrow: "Teach routing decisions", title: "Tune from reviewed examples",
          subtitle: "Review uncertain examples, preserve sealed test data, and inspect a staged candidate before accepting it for the next round.")
        GroupBox("Prepare an experiment · no model calls") {
          VStack(alignment: .leading, spacing: 12) {
            HStack {
              TextField("Example file · CSV, JSONL, JSON or YAML", text: $source)
              Button("Choose…") {
                let panel = NSOpenPanel()
                panel.canChooseDirectories = false
                if panel.runModal() == .OK { source = panel.url?.path ?? "" }
              }
            }
            Text("Provide at least six distinct examples with state and optional label columns. Unlabeled pools use uncertainty selection plus random audit examples.")
              .font(.caption).foregroundStyle(.secondary)
            HStack {
              TextField("Question pack", text: $pack)
              TextField("Reflection provider/model", text: $reflection)
            }
            HStack {
              Stepper("Optimization evaluations: \(evaluations)", value: $evaluations, in: 1...1000)
              Stepper("Review batch: \(batch)", value: $batch, in: 2...20)
            }
            HStack {
              Text("Reflection budget ($)")
              TextField("USD", value: $cost, format: .number).frame(width: 90)
              Spacer()
              Button("Try practice examples · no calls") {
                request("tuning.prepare", ["practice": true, "reflection_model": reflection,
                  "max_evals": evaluations, "max_cost": cost, "batch_size": batch])
              }.disabled(blocked || app.projectID.isEmpty)
              Button("Prepare examples") {
                request("tuning.prepare", ["data": source, "pack": pack,
                  "reflection_model": reflection, "max_evals": evaluations,
                  "max_cost": cost, "batch_size": batch])
              }.disabled(blocked || source.isEmpty || reflection.isEmpty)
            }
          }.textFieldStyle(.roundedBorder).padding(10)
        }
        HStack {
          Picker("Saved experiment", selection: $selected) {
            Text("Choose an experiment").tag("")
            ForEach(sessions, id: \.projectRowID) { row in
              Text(String(string(row, "id").prefix(16))).tag(string(row, "id"))
            }
          }
          Button("Refresh") { Task { await refresh() } }.disabled(busy)
        }
        if !failure.isEmpty { Text(failure).foregroundStyle(.orange).textSelection(.enabled) }
        if busy { ProgressView("Loading tuning state…") }
        if !current.isEmpty { roundView }
        if string(app.detail, "kind") == "tuning" {
          HStack {
            Text("Live tuning: " + string(app.detail, "status"))
            Spacer()
            if app.active { Button("Stop run", role: .destructive, action: app.cancel) }
          }
          EventStream().frame(height: 220)
        }
      }.padding(24)
    }
    .task(id: app.projectID) {
      selected = initialExperimentID
      current = [:]
      await refresh()
    }
    .task(id: String(app.active)) {
      if !app.active && !selected.isEmpty { request("tuning.get", ["id": selected]) }
    }
    .onChange(of: selected) { _, value in
      current = [:]
      label = ""
      rationale = ""
      if !value.isEmpty { request("tuning.get", ["id": value]) }
    }
  }

  private var roundView: some View {
    VStack(alignment: .leading, spacing: 14) {
      let counts = current["counts"] as? [String: Any] ?? [:]
      let options = current["options"] as? [String: Any] ?? [:]
      if current["synthetic_practice"] as? Bool == true {
        Label("Synthetic practice · not benchmark evidence", systemImage: "graduationcap")
          .font(.headline).foregroundStyle(.secondary)
        Text("One example is pre-labeled. Practice judging the rest without model calls. Practice mode cannot run live optimization or authorize adoption. Prepare real examples when you are ready for a measured experiment.")
          .font(.caption).foregroundStyle(.secondary)
      }
      HStack {
        Text("Round \(String(describing: current["round"] ?? 1))").font(.title2)
        Pill(title: string(current, "status"))
        Text("\(String(describing: counts["train"] ?? 0)) train · \(String(describing: counts["validation"] ?? 0)) validation · \(String(describing: counts["test"] ?? 0)) sealed test")
          .font(.caption)
      }
      Text("Reflection: \(string(options, "reflection_lm")) · up to \(String(describing: options["max_evals"] ?? 0)) optimization evaluations · $\(String(describing: options["max_reflection_cost"] ?? 0)) reflection ceiling. Jev usage, retries and final test evaluations are additional.")
        .font(.caption).foregroundStyle(.secondary)
      if current["needs_acquisition"] as? Bool == true {
        Text("Select the next review batch using uncertainty and a random audit sample. This makes Jev calls.")
        Button("Select examples…") { start("acquire") }.disabled(blocked)
      } else if !example.isEmpty {
        GroupBox("Review example " + string(example, "id")) {
          VStack(alignment: .leading, spacing: 12) {
            Text(string(example, "split") == "test" ? "Reserved test example · labels stay outside optimizer training" : "Development example")
              .font(.caption).foregroundStyle(.secondary)
            CodeBlock(text: pretty(example["state"])).frame(height: 160)
            Picker("Correct decision", selection: $label) {
              Text("Choose a label").tag("")
              ForEach(current["labels"] as? [String] ?? [], id: \.self) { Text($0).tag($0) }
            }
            TextField("Why? Optional rationale", text: $rationale).textFieldStyle(.roundedBorder)
            Button("Save judgment and continue") {
              request("tuning.label", ["id": selected, "revision": string(current, "revision"),
                "example": string(example, "id"), "label": label, "rationale": rationale])
            }.disabled(blocked || label.isEmpty)
            Text("\(rows.count) judgments remaining in this review batch. Saved judgments survive closing this window.")
              .font(.caption).foregroundStyle(.secondary)
            DisclosureGroup("Selection evidence") { CodeBlock(text: pretty(example)).frame(height: 180) }
          }.padding(10)
        }
      } else if string(current, "status") == "review", current["synthetic_practice"] as? Bool == true {
        Text("Practice complete. Prepare a file of your real examples above to start a measured experiment.")
          .font(.callout).foregroundStyle(.secondary)
      } else if string(current, "status") == "review" {
        Button("Run bounded optimization…") { start("optimize") }.disabled(blocked)
      }
      if let report = current["report"] as? [String: Any] {
        Pill(title: current["synthetic_practice"] as? Bool == true ? "PRACTICE ONLY" : report["eligible"] as? Bool == true ? "VERIFIED CANDIDATE" : "MORE EVIDENCE REQUIRED",
          color: current["synthetic_practice"] as? Bool == true ? .secondary : report["eligible"] as? Bool == true ? .green : .orange)
        if string(current, "status") == "decision" {
          HStack {
            Button("Accept for next round") { decide("accept") }
              .disabled(blocked || report["eligible"] as? Bool != true || current["synthetic_practice"] as? Bool == true)
            Button("Reject candidate") { decide("reject") }.disabled(blocked)
          }
          Text("Accepting advances this experiment's staged pack. It does not activate or overwrite your project harness.")
            .font(.caption).foregroundStyle(.secondary)
        }
        DisclosureGroup("Full tuning report") { CodeBlock(text: pretty(report)).frame(height: 300) }
      }
      if string(current, "status") == "running" && !app.active {
        Text("An interrupted worker may have left a lock. Inspect the saved experiment before recovery; do not delete locks or restart a budget automatically.")
          .font(.callout).foregroundStyle(.orange)
      }
    }
  }

  private func decide(_ decision: String) {
    guard app.confirm("\(decision.capitalized) staged candidate?", "This records your judgment for this experiment. The active project harness is unchanged.", button: decision.capitalized) else { return }
    request("tuning.decide", ["id": selected, "revision": string(current, "revision"), "decision": decision])
  }
  private func start(_ stage: String) {
    guard app.confirm(stage == "acquire" ? "Select examples with Jev?" : "Start live tuning?",
      "This makes model calls using the saved experiment budgets. Reflection limits exclude Jev usage, retries and final test evaluations. Interrupted runs are not automatically replayed.", button: "Start live run") else { return }
    app.start("tuning.start", extra: ["id": selected, "revision": string(current, "revision"), "stage": stage, "live": true])
  }
  private func request(_ method: String, _ values: [String: Any]) {
    let project = app.projectID
    let identity = selected
    busy = true
    failure = ""
    Task {
      defer { busy = false }
      do {
        let result = try await app.engine.call(method, values.merging(["project": project]) { _, new in new }) as? [String: Any] ?? [:]
        guard project == app.projectID, identity == selected else { return }
        if method == "tuning.prepare" {
          sessions.insert(["id": string(result, "id")], at: 0)
          selected = string(result, "id")
        }
        current = result
        label = ""
        rationale = ""
      } catch {
        guard project == app.projectID, identity == selected else { return }
        failure = error.localizedDescription
      }
    }
  }
  private func refresh() async {
    let project = app.projectID
    do {
      let result = try await app.engine.call("tuning.list", ["project": project]) as? [[String: Any]] ?? []
      guard !Task.isCancelled, project == app.projectID else { return }
      sessions = result
      if !selected.isEmpty { request("tuning.get", ["id": selected]) }
    } catch {
      guard project == app.projectID else { return }
      failure = error.localizedDescription
    }
  }
}
