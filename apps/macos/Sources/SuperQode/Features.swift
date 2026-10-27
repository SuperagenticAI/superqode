import AppKit
import SwiftUI
import UniformTypeIdentifiers

struct HubView: View {
  @EnvironmentObject var app: Workspace
  @State private var search = ""
  @State private var filter = "All"
  @State private var selected: [String: Any]?
  @State private var spec: [String: Any] = [:]
  var rows: [[String: Any]] {
    app.hub.filter { row in
      (search.isEmpty
        || ["name", "description", "runtime", "category"].map { string(row, $0) }.joined(
          separator: " "
        ).localizedCaseInsensitiveContains(search))
        && (filter == "All"
          || (filter == "Native"
            && ["native", "preset"].contains(string(row, "integration_level")))
          || (filter == "Ready" && string(row, "readiness") == "ready")
          || (filter == "Needs setup" && string(row, "readiness") == "setup-required"))
    }
  }
  func definition(_ row: [String: Any]) -> [String: Any]? {
    app.harnesses.first {
      [string(row, "id"), "connection:" + string(row, "id"), "attach:" + string(row, "id")]
        .contains(string($0, "id"))
        || (!string(row, "project_path").isEmpty
          && string($0, "path") == string(row, "project_path"))
    }
  }
  var body: some View {
    VStack(alignment: .leading, spacing: 24) {
      PageTitle(
        eyebrow: "One Agent Space. Many ways to build.", title: "Harness Hub",
        subtitle:
          "Discover runtimes, inspect capabilities and choose how your agent works. Compare and improve the harnesses you use."
      )
      HStack {
        TextField("Search harnesses, runtimes, capabilities", text: $search).textFieldStyle(
          .roundedBorder
        ).frame(maxWidth: 400)
        Spacer()
        Picker("Filter", selection: $filter) {
          ForEach(["All", "Native", "Ready", "Needs setup"], id: \.self) { Text($0) }
        }.frame(width: 170)
        Pill(title: "\(rows.count) HARNESSES", color: .qAccent)
      }
      ScrollView {
        LazyVGrid(columns: [GridItem(.adaptive(minimum: 255), spacing: 16)], spacing: 16) {
          ForEach(rows, id: \.projectRowID) { row in
            Button {
              selected = row
              spec = [:]
              if let def = definition(row) {
                app.perform {
                  spec =
                    try await app.engine.call(
                      "harnesses.inspect",
                      ["project": app.projectID, "reference": string(def, "id")]) as? [String: Any]
                    ?? [:]
                }
              }
            } label: {
              VStack(alignment: .leading, spacing: 14) {
                HStack {
                  Image(
                    systemName: string(row, "integration_level") == "native"
                      ? "diamond" : "square.stack.3d.up"
                  ).font(.title2).foregroundStyle(Color.qAccent)
                  Spacer()
                  Pill(
                    title: string(row, "readiness", "catalog"),
                    color: string(row, "readiness") == "ready" ? .green : .secondary)
                }
                Text(string(row, "name")).font(.system(size: 16, weight: .semibold)).lineLimit(1)
                Text(string(row, "description")).font(.system(size: 12)).foregroundStyle(.secondary)
                  .lineLimit(3).frame(height: 48, alignment: .top)
                Divider()
                HStack {
                  Text(string(row, "runtime", string(row, "category"))).font(
                    .system(size: 11, design: .monospaced)
                  ).foregroundStyle(.secondary)
                  Spacer()
                  Text(definition(row) == nil ? "CONNECTION" : "INSPECT →").font(
                    .system(size: 11, weight: .semibold, design: .monospaced)
                  ).foregroundStyle(Color.qAccent)
                }
              }.padding(20).brandSurface(radius: 12)
                .overlay(RoundedRectangle(cornerRadius: 12).stroke(.primary.opacity(0.08)))
            }.buttonStyle(.plain)
          }
        }.padding(.bottom, 20)
      }
    }.padding(30).centeredDialog(
      isPresented: Binding(get: { selected != nil }, set: { if !$0 { selected = nil } })
    ) {
      if let row = selected {
        VStack(alignment: .leading, spacing: 18) {
          HStack {
            Text(string(row, "name")).font(.title)
            Spacer()
            nativeButton("dialog.done", action: { selected = nil }, title: "Done") { Text("Done") }
          }
          Text(string(row, "description")).foregroundStyle(.secondary)
          HStack {
            Pill(title: string(row, "runtime", "catalog"))
            Pill(title: string(row, "readiness", "setup required"))
            Pill(title: string(row, "openness", "unknown"))
          }
          if let def = definition(row) {
            CodeBlock(text: pretty(spec))
            HStack {
              Button(string(def, "desktop_kind").isEmpty ? "Use harness" : "Use connection") {
                use(def, "Workspace")
              }.buttonStyle(BrandButtonStyle()).disabled(def["available"] as? Bool != true)
              if string(def, "desktop_kind").isEmpty {
                Button("Evaluate") { use(def, "Evaluations") }
                Button("Optimize") { use(def, "Optimization") }
              }
            }
            if !string(def, "issue").isEmpty {
              Text(string(def, "issue")).font(.caption).foregroundStyle(.orange)
            }
          } else {
            CodeBlock(text: pretty(row))
            Text(
              "This connection is listed in the shared catalog. Its native desktop execution adapter is not available yet; use the existing terminal workflow."
            ).font(.callout).foregroundStyle(.secondary)
          }
        }.padding(28).frame(width: 740, height: 600)
      }
    }
  }
  func use(_ definition: [String: Any], _ destination: String) {
    if destination == "Workspace", ["acp", "connection"].contains(string(definition, "desktop_kind")) {
      app.chooseConnection(definition)
    } else {
      app.chooseHarness(string(definition, "id"))
    }
    app.section = destination
    app.savePreferences()
    selected = nil
  }
}
struct ModelsView: View {
  @EnvironmentObject var app: Workspace
  var body: some View {
    VStack(alignment: .leading, spacing: 24) {
      PageTitle(
        eyebrow: "Your compute. Your choice.", title: "Models on your Mac",
        subtitle:
          "Use local inference or your existing provider credentials. Model weights and keys remain under your control."
      )
      HStack(spacing: 18) {
        Metric(label: "CHIP", value: string(app.hardware, "chip", "Mac"))
        Metric(label: "UNIFIED MEMORY", value: "\(app.hardware["unified_memory_gb"] ?? "—") GB")
        Metric(label: "DISCOVERED MODELS", value: "\(app.models.count)")
        Spacer()
        Button("Refresh") {
          app.perform {
            await app.refreshModels()
            await app.refreshProviders()
            await app.checkRoute()
          }
        }
        Button("Connect…") { app.showConnection = true }.disabled(app.project.isEmpty).buttonStyle(
          BrandButtonStyle())
      }
      GroupBox("Active model route") {
        VStack(alignment: .leading, spacing: 14) {
          RouteControls()
          RouteReadiness()
          HStack {
            Text(
              "Use a saved Keychain credential, an existing local configuration, or a local model."
            ).font(.caption).foregroundStyle(.secondary)
            Spacer()
            Button("Save route", action: app.savePreferences)
            Button("Test model", action: app.testConnection).disabled(
              app.model.isEmpty || app.busy || app.anyActive || app.isACP)
            if !app.selectedJob.isEmpty { Button("View run") { app.section = "Workspace" } }
          }
        }.padding(12)
      }
      ScrollView {
        LazyVStack(spacing: 10) {
          if app.models.isEmpty {
            EmptyState(
              icon: "cpu", title: "No local models discovered",
              detail:
                "Start your local inference server, then refresh. You can also enter a provider and model ID above."
            ).frame(height: 180)
          }
          ForEach(Array(app.models.enumerated()), id: \.offset) { _, row in
            HStack(spacing: 16) {
              Image(systemName: "cpu").font(.title2).foregroundStyle(Color.qAccent)
              VStack(alignment: .leading, spacing: 6) {
                Text(string(row, "model_id")).font(.headline)
                Text(
                  string(row, "source") + " · "
                    + String(format: "%.1f", row["size_gb"] as? Double ?? 0) + " GB"
                ).font(.caption.monospaced()).foregroundStyle(.secondary)
              }
              Spacer()
              if row["loaded"] as? Bool == true { Pill(title: "LOADED", color: .green) }
              if string(row, "source").lowercased().contains("ollama") {
                Button("Use model") {
                  app.chooseModelRoute("ollama", modelName(string(row, "model_id")))
                  app.notice = "Model route updated."
                }.disabled(
                  string(row, "model_id").localizedCaseInsensitiveContains("embed")
                    || string(row, "model_id").localizedCaseInsensitiveContains("rerank")
                ).help("Embedding and reranking models cannot run coding tasks.")
              } else {
                Pill(title: "WEIGHTS ON DISK")
              }
            }.padding(18).brandSurface(radius: 10)
          }
        }
      }
    }.padding(30)
  }
}
struct Metric: View {
  var label: String
  var value: String
  var body: some View {
    VStack(alignment: .leading, spacing: 8) {
      Text(label).font(.system(size: 11, design: .monospaced)).foregroundStyle(.secondary)
      Text(value).font(.system(size: 20, weight: .medium))
    }.padding(18).frame(minWidth: 140, alignment: .leading).outlinedSurface(radius: 9)
  }
}
struct EvaluationView: View { var body: some View { ExperimentView(optimize: false) } }
struct OptimizationView: View { var body: some View { ExperimentView(optimize: true) } }
struct ExperimentView: View {
  @EnvironmentObject var app: Workspace
  let optimize: Bool
  @State private var suite = ""
  @State private var variant = ""
  @State private var live = false
  @State private var maxEvals = 4
  @State private var maxCost = 1.0
  @State private var reflection = ""
  @State private var optimizer = ""
  @State private var imported: [String: Any]?
  @State private var split = "all"
  @State private var diagnostics: [String: Any] = [:]
  @State private var diagnosticError = ""
  @State private var inspecting = false
  @State private var history: [[String: Any]] = []
  @State private var historyError = ""
  @State private var workflow: String?
  @State private var showTuning = false
  @State private var configurationMode: String?
  private var candidates: [String] {
    variant.components(separatedBy: "\n").map { $0.trimmingCharacters(in: .whitespacesAndNewlines) }.filter { !$0.isEmpty }
  }
  private var inspectionKey: String { app.projectID + "\n" + suite + "\n" + split + "\n" + variant }
  var result: [String: Any] { imported ?? (app.detail["result"] as? [String: Any] ?? [:]) }
  var relevant: Bool { string(app.detail, "kind") == (optimize ? "optimization" : "evaluation") }
  var body: some View {
    ScrollView {
      VStack(alignment: .leading, spacing: 24) {
        HStack(alignment: .top) {
          PageTitle(
            eyebrow: optimize ? "Improve with evidence" : "Measure what matters",
            title: optimize ? "Make your harness better." : "Know what your harness can do.",
            subtitle: optimize
              ? "Explore candidate configurations, inspect the trade-offs and keep the evidence. Adopt improvements only after their gates pass."
              : "Compare configurations on the same tasks. Inspect wins, failures and regressions before choosing a harness."
          )
          Menu("More harness workflows") {
            Button("Build a harness…") { configurationMode = "wizard" }
            Button("Configure RLM routing…") { configurationMode = "rlm-routing" }
            Button("Configure RLM budgets…") { configurationMode = "rlm" }
            Divider()
            Button("Tune routing decisions from examples…") { showTuning = true }
            Button("Reproducible benchmarks…") { workflow = "harness bench" }
            Button("Mine failures…") { workflow = "harness mine-failures" }
            Button("Additional optimization engines…") { workflow = "harness optimize" }
            Button("Improve from failures…") { workflow = "harness improve" }
            Button("Validate harness…") { workflow = "harness doctor" }
            Button("Candidate ledger…") { workflow = "harness optimize-ledger" }
            Button("Promotion status…") { workflow = "harness promote status" }
            Button("Stage a revision…") { workflow = "harness promote stage" }
            Button("Canary validation…") { workflow = "harness promote canary" }
            Button("Activate a revision…") { workflow = "harness promote activate" }
            Button("Roll back a revision…") { workflow = "harness promote rollback" }
          }
          Button("Open result…", action: importResult)
        }
        GroupBox {
          VStack(alignment: .leading, spacing: 18) {
            RouteControls(allowACP: false)
            if app.isACP {
              Text("Choose a built-in or project harness above for evaluation. ACP subscription routes are not supported by this evaluator.")
                .font(.caption).foregroundStyle(.secondary)
            } else if live && app.model.isEmpty {
              Text("Select a provider and model for live execution. Setup checks do not require a model or API key.")
                .font(.caption).foregroundStyle(.secondary)
            }
            Divider()
            HStack {
              Picker("Evaluation suite", selection: $suite) {
                Text("Choose a suite").tag("")
                ForEach(app.packs, id: \.projectRowID) { pack in
                  Text(string(pack, "name")).tag(string(pack, "path"))
                }
                if !suite.isEmpty && !app.packs.contains(where: { string($0, "path") == suite }) {
                  Text(URL(fileURLWithPath: suite).lastPathComponent).tag(suite)
                }
              }.frame(maxWidth: 550)
              Button("Custom suite…") { chooseFile { suite = $0 } }
            }
            if optimize {
              HStack {
                Stepper("Evaluation limit: \(maxEvals)", value: $maxEvals, in: 1...100).frame(
                  width: 230)
                Text("Cost limit ($)")
                TextField("USD", value: $maxCost, format: .number).frame(width: 90).textFieldStyle(
                  .roundedBorder)
              }
              HStack {
                TextField("Reflection model: provider/model", text: $reflection)
                TextField("Optimizer model ID", text: $optimizer)
              }.textFieldStyle(.roundedBorder)
              Toggle(
                "Allow live optimization and model charges within the configured limits",
                isOn: $live
              ).font(.callout)
              if app.capabilities["omni"] as? Bool != true {
                Label(
                  "Compatible Omni optimization runtime is unavailable in this build.",
                  systemImage: "exclamationmark.triangle"
                ).font(.caption).foregroundStyle(.orange)
              }
              Text(
                "Candidates are staged for review. Provider cost reporting can lag; the cost limit is an engine budget, not a billing guarantee."
              ).font(.caption).foregroundStyle(.secondary)
            } else {
              Picker("Task split", selection: $split) {
                Text("All tasks").tag("all")
                Text("Held-in · development").tag("held-in")
                Text("Held-out · validation").tag("held-out")
              }.frame(maxWidth: 550)
              Text("Candidate HarnessSpec paths · one per line, up to eight").font(.caption)
              TextEditor(text: $variant).font(.caption.monospaced()).frame(height: 65)
                .outlinedSurface(radius: 6)
              Button("Add candidate…") {
                chooseFile { variant += (variant.isEmpty ? "" : "\n") + $0 }
              }
              Toggle("Live evaluation · run harnesses and allow model charges", isOn: $live)
              Text(
                live
                  ? "Live evaluations execute suite tasks using the selected route."
                  : "Setup check validates the configuration and skips execution. It does not measure coding quality."
              ).font(.caption).foregroundStyle(.secondary)
            }
            suiteDiagnostics
            HStack {
              Pill(
                title: live ? "LIVE EXECUTION" : "SETUP CHECK", color: live ? .orange : .secondary)
              Spacer()
              if relevant && app.active {
                Button("Stop run", role: .destructive, action: app.cancel)
              }
              Button(optimize ? "Optimize harness" : live ? "Run evaluation" : "Check setup") {
                start()
              }.buttonStyle(BrandButtonStyle()).disabled(
                suite.isEmpty || (live && app.model.isEmpty) || app.busy || app.anyActive || app.isACP
                  || inspecting || !diagnosticError.isEmpty || diagnostics.isEmpty
                  || (diagnostics["task_count"] as? Int ?? 0) == 0
                  || (optimize && diagnostics["optimization_ready"] as? Bool != true)
                  || (optimize
                    && (!live || reflection.isEmpty || optimizer.isEmpty
                      || app.capabilities["omni"] as? Bool != true))
              )
            }
          }.padding(14)
        }
        experimentHistory
        if imported != nil || relevant {
          HStack {
            Text("Run evidence").font(.title3.weight(.medium))
            Spacer()
            if relevant {
              Pill(title: string(app.detail, "status"), color: app.active ? .orange : .qAccent)
              Button("Export…", action: app.exportEvidence)
            }
          }
          if !result.isEmpty {
            if optimize { optimizationResult } else { EvaluationResult(result: result) }
          }
          if relevant {
            EventStream().frame(height: 300).outlinedSurface(radius: 10)
          }
        } else {
          EmptyState(
            icon: optimize ? "slider.horizontal.3" : "checkmark.seal",
            title: optimize ? "Evidence before adoption" : "Your scorecard starts here",
            detail: optimize
              ? "Optimize prompts and harness settings against a suite, then inspect the candidate diff before saving a new harness."
              : "Choose a suite and baseline. Add a candidate to compare per-task outcomes and detect regressions."
          ).frame(height: 220)
        }
      }.padding(30)
    }.onAppear { if suite.isEmpty { suite = app.packs.first.map { string($0, "path") } ?? "" } }
      .task(id: inspectionKey) { await inspectSuite() }
      .task(id: app.projectID + app.selectedJob + String(app.active)) { await loadHistory() }
      .sheet(isPresented: $showTuning) {
        VStack {
          HStack { Spacer(); Button("Done") { showTuning = false } }.padding()
          TuningView().environmentObject(app)
        }.frame(minWidth: 850, minHeight: 700)
      }
      .sheet(isPresented: Binding(get: { configurationMode != nil }, set: { if !$0 { configurationMode = nil } })) {
        VStack {
          HStack { Spacer(); Button("Done") { configurationMode = nil } }.padding()
          HarnessConfigurationView(mode: configurationMode ?? "wizard") { reference in
            app.chooseHarness(reference)
            app.savePreferences()
            configurationMode = nil
          }.environmentObject(app)
        }.frame(minWidth: 760, minHeight: 650)
      }
      .sheet(isPresented: Binding(get: { workflow != nil }, set: { if !$0 { workflow = nil } })) {
        VStack {
          HStack { Spacer(); Button("Done") { workflow = nil } }.padding()
          ToolsView(workflow: workflow).environmentObject(app)
        }.frame(minWidth: 1000, minHeight: 700)
      }
  }
  private var suiteDiagnostics: some View {
    VStack(alignment: .leading, spacing: 8) {
      if inspecting { ProgressView("Checking suite…") }
      if !diagnosticError.isEmpty {
        Text(diagnosticError).font(.callout).foregroundStyle(.orange)
      }
      if !diagnostics.isEmpty {
        let counts = diagnostics["split_counts"] as? [String: Any] ?? [:]
        Text("Suite: \(String(describing: diagnostics["task_count"] ?? 0)) selected · \(String(describing: counts["held-in"] ?? 0)) held-in · \(String(describing: counts["held-out"] ?? 0)) held-out")
          .font(.caption.monospaced())
        if !optimize {
          Text("Configurations: baseline + \(String(describing: diagnostics["candidate_count"] ?? 0)) candidates").font(.caption)
        }
        Text(string(diagnostics, "tasks_hash")).font(.caption2.monospaced()).textSelection(.enabled)
        ForEach(diagnostics["warnings"] as? [String] ?? [], id: \.self) { warning in
          Label(warning, systemImage: "exclamationmark.triangle").font(.caption).foregroundStyle(.orange)
        }
      }
    }
  }
  private var experimentHistory: some View {
    GroupBox("Experiment history · latest 100 for this project") {
      VStack(alignment: .leading, spacing: 10) {
        HStack {
          Text("Reopen evidence without starting another run.").font(.caption).foregroundStyle(.secondary)
          Spacer()
          Button("Refresh") { Task { await loadHistory() } }
        }
        if !historyError.isEmpty { Text(historyError).foregroundStyle(.orange) }
        if history.isEmpty { Text("No experiments recorded yet.").font(.caption) }
        ForEach(history.filter { string($0, "kind") == (optimize ? "optimization" : "evaluation") }, id: \.projectRowID) { row in
          Button {
            imported = nil
            app.candidate = [:]
            app.selectJob(string(row, "id"))
          } label: {
            HStack {
              Text(string(row, "title")).lineLimit(1)
              Text(String(string(row, "id").prefix(12))).font(.caption.monospaced())
              Spacer()
              Text(string(row, "status")).font(.caption)
            }
          }.buttonStyle(.plain)
        }
      }.padding(10)
    }
  }
  func inspectSuite() async {
    let key = inspectionKey
    diagnostics = [:]
    diagnosticError = ""
    inspecting = false
    guard !suite.isEmpty, !app.projectID.isEmpty else { return }
    inspecting = true
    defer { if key == inspectionKey { inspecting = false } }
    do {
      let value = try await app.engine.call("evals.inspect", [
        "project": app.projectID, "tasks": suite, "split": optimize ? "all" : split,
        "variants": optimize ? [] : candidates,
      ]) as? [String: Any] ?? [:]
      guard !Task.isCancelled, key == inspectionKey else { return }
      diagnostics = value
    } catch {
      guard !Task.isCancelled, key == inspectionKey else { return }
      diagnosticError = error.localizedDescription
    }
  }
  func loadHistory() async {
    let project = app.projectID
    history = []
    historyError = ""
    guard !project.isEmpty else { return }
    do {
      let rows = try await app.engine.call("experiments.list", ["project": project]) as? [[String: Any]] ?? []
      guard !Task.isCancelled, project == app.projectID else { return }
      history = rows
    } catch {
      guard !Task.isCancelled, project == app.projectID else { return }
      historyError = error.localizedDescription
    }
  }
  private var adoptionPassed: Bool {
    (result["adoption_gate"] as? [String: Any])?["accepted"] as? Bool == true
  }
  var optimizationResult: some View {
    VStack(alignment: .leading, spacing: 16) {
      HStack {
        Metric(label: "BASELINE SCORE", value: String(describing: result["baseline_score"] ?? "—"))
        Metric(label: "CANDIDATE SCORE", value: String(describing: result["best_score"] ?? "—"))
        Pill(
          title: imported != nil ? "IMPORTED EVIDENCE" : adoptionPassed ? "GATE PASSED" : "REVIEW REQUIRED",
          color: imported != nil ? .secondary : adoptionPassed ? .green : .orange)
      }
      ForEach((result["adoption_gate"] as? [String: Any])?["issues"] as? [String] ?? [], id: \.self) { issue in
        Label(issue, systemImage: "exclamationmark.triangle").font(.caption).foregroundStyle(.orange)
      }
      EvaluationComparisonView(comparison: result["comparison"] as? [String: Any] ?? [:])
      if relevant && imported == nil {
        HStack {
          Button("Inspect candidate diff", action: app.inspectCandidate)
          if !app.candidate.isEmpty {
            Button("Save as new harness", action: app.saveCandidate).disabled(
              app.candidate["accepted"] as? Bool != true
                || app.candidate["unchanged"] as? Bool != true)
          }
        }
        if !app.candidate.isEmpty {
          DiffView(text: string(app.candidate, "diff")).frame(height: 260)
        }
      }
      DisclosureGroup("Full optimization evidence") {
        CodeBlock(text: pretty(result)).frame(height: 300)
      }
    }
  }
  func chooseFile(_ selected: (String) -> Void) {
    let panel = NSOpenPanel()
    panel.canChooseDirectories = false
    panel.allowsMultipleSelection = false
    if panel.runModal() == .OK, let path = panel.url?.path { selected(path) }
  }
  func importResult() {
    chooseFile { path in
      app.perform {
        // This permission is set only after the native file picker selected the path.
        let raw =
          try await app.engine.call(
            "artifacts.read", ["project": app.projectID, "path": path, "_approved_artifact": true])
          as? [String: Any] ?? [:]
        imported =
          (raw["job"] as? [String: Any])?["result"] as? [String: Any] ?? raw["result"]
          as? [String: Any] ?? raw
      }
    }
  }
  func start() {
    if live
      && !app.confirm(
        optimize ? "Start live optimization?" : "Start live evaluation?",
        optimize
          ? "Allow model calls with up to \(maxEvals) evaluations and a $\(maxCost) engine cost budget. Tasks execute on this Mac."
          : "This suite will run tasks and may incur provider charges.", button: "Start run")
    {
      return
    }
    imported = nil
    var params: [String: Any] = ["tasks": suite, "live": live]
    if optimize {
      params.merge([
        "method": "omni", "max_evals": maxEvals, "max_cost": maxCost,
        "reflection_model": reflection, "optimizer_model": optimizer,
      ]) { _, new in new }
    } else {
      params["variants"] = candidates
      params["split"] = split
    }
    app.start(optimize ? "optimizations.start" : "evaluations.start", extra: params)
  }
}
struct EvaluationResult: View {
  let result: [String: Any]
  var live: Bool { result["live"] as? Bool == true }
  var variants: [[String: Any]] { result["variants"] as? [[String: Any]] ?? [] }
  var body: some View {
    VStack(alignment: .leading, spacing: 18) {
      Label(
        !live
          ? "Setup checked · execution skipped"
          : result["regressed"] as? Bool == true ? "Regression detected" : "Evaluation recorded",
        systemImage: !live
          ? "info.circle"
          : result["regressed"] as? Bool == true ? "exclamationmark.triangle" : "chart.bar"
      ).font(.headline).foregroundStyle(
        !live ? Color.secondary : result["regressed"] as? Bool == true ? .orange : .secondary)
      HStack {
        Metric(label: "SUITE CASES", value: String(describing: result["task_count"] ?? "—"))
        Metric(label: "CONFIGURATIONS", value: "\(variants.count)")
        Metric(label: "DURATION", value: "\(result["duration_seconds"] ?? "—")s")
      }
      EvaluationComparisonView(comparison: result["comparison"] as? [String: Any] ?? [:])
      ForEach(Array(variants.enumerated()), id: \.offset) { index, variant in
        GroupBox {
          VStack(alignment: .leading, spacing: 12) {
            HStack {
              Text(string(variant, "harness")).font(.headline)
              Pill(title: index == 0 ? "BASELINE" : "CANDIDATE")
              Spacer()
              Text(live ? String(format: "%.0f%%", (variant["score"] as? Double ?? 0) * 100) : "—")
                .font(.title2.monospaced())
            }
            Text(variantSummary(variant)).font(.caption.monospaced()).foregroundStyle(.secondary)
            ForEach(Array((variant["tasks"] as? [[String: Any]] ?? []).enumerated()), id: \.offset)
            { _, task in
              DisclosureGroup {
                CodeBlock(text: pretty(task)).frame(height: 170)
              } label: {
                HStack {
                  Text(string(task, "id"))
                  Spacer()
                  Text(string(task, "split")).foregroundStyle(.secondary)
                  Pill(title: string(task, "status"))
                }
              }.font(.caption)
            }
          }.padding(12)
        }
      }
      Text("Suite hash: " + string(result, "tasks_hash", "not recorded")).font(
        .system(size: 11, design: .monospaced)
      ).foregroundStyle(.secondary).textSelection(.enabled)
    }
  }

  private func variantSummary(_ variant: [String: Any]) -> String {
    let passed = String(describing: variant["passed"] ?? 0)
    let failed = String(describing: variant["failed"] ?? 0)
    let skipped = String(describing: variant["skipped"] ?? 0)
    let cost = (variant["cost_usd"] as? Double).flatMap {
      $0.isFinite && $0 >= 0 ? String(format: "$%.4f", $0) : nil
    } ?? "Cost unknown"
    return "\(passed) passed · \(failed) failed · \(skipped) skipped · \(cost)"
  }
}
struct FilesView: View {
  @EnvironmentObject var app: Workspace
  @State private var search = ""
  @State private var visibleFiles: [String] = []
  @State private var creating = false
  @State private var newPath = ""
  private var selected: String { app.selectedFile }
  @State private var content = ""
  @State private var original = ""
  @State private var digest = ""
  @State private var loadedProject = ""
  @State private var loadedPath = ""
  @State private var diskContent = ""
  @State private var fileIssue = ""
  @State private var conflicted = false
  @State private var comparing = false
  @State private var editing = false
  @State private var loading = false
  @State private var saving = false
  @State private var loadGeneration = 0
  private var dirty: Bool { content != original }
  private var draftKey: String { loadedProject + "\n" + loadedPath }
  var body: some View {
    VStack(alignment: .leading, spacing: 20) {
      PageTitle(
        eyebrow: "Stay close to the code", title: "Project files",
        subtitle:
          "Read and edit project source files here. Save with a revision check, then review the diff."
      )
      if !app.recoveredFilePaths.isEmpty {
        Menu("Recovered drafts (\(app.recoveredFilePaths.count))") {
          ForEach(app.recoveredFilePaths, id: \.self) { path in
            Button(path) { app.selectedFile = path }
          }
        }.disabled(saving).help("Open an unsaved file draft, including files no longer on disk")
      }
      if !fileIssue.isEmpty {
        Label(fileIssue, systemImage: "exclamationmark.triangle")
          .font(.callout).foregroundStyle(.orange).textSelection(.enabled)
      }
      HSplitView {
        VStack {
          HStack {
            TextField("Find a file", text: $search).textFieldStyle(.roundedBorder)
            Button {
              newPath = ""
              creating = true
            } label: {
              Image(systemName: "doc.badge.plus")
            }.help("New source file").disabled(app.anyActive || saving)
          }
          List(
            visibleFiles,
            id: \.self, selection: $app.selectedFile
          ) { Text($0).font(.system(size: 11, design: .monospaced)).tag($0) }
            .scrollContentBackground(.hidden).background(Color.qPanel).disabled(saving)
        }.frame(minWidth: 220, idealWidth: 300, maxWidth: 400)
        VStack(alignment: .leading, spacing: 12) {
          fileToolbar
          SourceEditor(text: Binding(get: { content }, set: { content = $0; stash() }),
            path: loadedPath, editable: editing, documentID: loadedProject + "\n" + loadedPath)
            .disabled(loading || saving).clipShape(RoundedRectangle(cornerRadius: 8))
            .overlay(RoundedRectangle(cornerRadius: 8).stroke(Color.primary.opacity(0.18), lineWidth: 1).allowsHitTesting(false))
          if app.anyActive {
            Text("Saving is paused while an agent or experiment is active in a project.").font(
              .caption
            ).foregroundStyle(.secondary)
          }
        }.padding(.leading, 12).frame(minWidth: 420)
      }
    }.padding(30).onAppear {
      loadedProject = app.projectID
      filterFiles()
      app.loadFiles()
      load()
    }
    .alert("New source file", isPresented: $creating) {
      TextField("Path relative to project", text: $newPath)
      Button("Create") { create() }
      Button("Cancel", role: .cancel) {}
    } message: {
      Text(
        "Enter a project path, such as Sources/Feature.swift. Parent folders are created as needed. Existing files are never overwritten."
      )
    }
    .onChange(of: search) { _, _ in filterFiles() }
    .onChange(of: app.files) { _, _ in filterFiles() }
    .onChange(of: app.recoveredFilePaths) { _, _ in filterFiles() }
    .onChange(of: app.selectedFile) { _, _ in stash(); load() }
    .onDisappear { stash(); app.flushRecovery(); loadGeneration += 1 }
    .centeredDialog(isPresented: $comparing, title: "Compare recovered edits") {
      VStack(alignment: .leading, spacing: 12) {
        Text(loadedPath).font(.headline.monospaced())
        Text("Saving still checks the original disk revision. Copy or Save As keeps your draft without replacing changed source.")
          .font(.callout).foregroundStyle(.secondary)
        HStack(alignment: .top) {
          comparisonColumn("Original revision", text: original)
          comparisonColumn("Current disk", text: diskContent)
          comparisonColumn("Your draft", text: content)
        }.frame(height: 420)
        Button("Close") { comparing = false }
      }.padding(20).frame(width: 900)
    }
  }
  private var fileToolbar: some View {
    HStack {
      Text(selected.isEmpty ? "Select a file" : selected).font(.caption.monospaced()).lineLimit(1)
      if dirty { Pill(title: "UNSAVED", color: .orange) }
      Spacer()
      Toggle("Edit", isOn: $editing).toggleStyle(.checkbox).disabled(selected.isEmpty)
      Menu("File actions") { fileActionItems }
        .disabled(selected.isEmpty || loading || saving)
      Button("Save", action: save).keyboardShortcut("s")
        .disabled(!dirty || digest.isEmpty || conflicted || loading || saving || app.anyActive)
    }
  }
  @ViewBuilder private var fileActionItems: some View {
    Button("Reload") {
      if !dirty
        || app.confirm(
          "Discard unsaved edits?",
          "Discard this recovered draft and read the current file from disk. Copy or save the draft first if you need it.", button: "Discard draft")
      {
        app.fileDrafts.removeValue(forKey: draftKey)
        app.flushRecovery()
        load()
      }
    }.disabled(selected.isEmpty || loading || saving)
    Button("Compare") { compare() }.disabled(selected.isEmpty || loading || saving)
    Button("Copy draft") {
      NSPasteboard.general.clearContents()
      NSPasteboard.general.setString(content, forType: .string)
    }.disabled(selected.isEmpty || loading)
    Button("Save As…", action: saveAs).disabled(selected.isEmpty || loading || saving || app.anyActive)
    Button("Stage file") {
      guard
        app.confirm(
          "Stage this file?",
          selected
            + " will be added to the index, including a new file if it is untracked.",
          button: "Stage file")
      else { return }
      let project = loadedProject
      let path = selected
      app.perform {
        _ = try await app.engine.call("git.stage_file", ["project": project, "path": path])
        await app.refreshGit()
      }
    }.disabled(selected.isEmpty || dirty || loading || saving || app.anyActive)
    Button("Unstage") {
      let project = loadedProject
      let path = selected
      app.perform {
        _ = try await app.engine.call(
          "git.unstage_file", ["project": project, "path": path])
        await app.refreshGit()
      }
    }.disabled(selected.isEmpty || loading || saving || app.anyActive)
    Button("Open in editor") {
      NSWorkspace.shared.open(
        URL(fileURLWithPath: string(app.project, "path")).appendingPathComponent(selected))
    }.disabled(selected.isEmpty)
  }
  private func create() {
    let project = loadedProject
    let path = newPath
    app.perform {
      let result =
        try await app.engine.call("files.create", ["project": project, "path": path])
        as? [String: Any] ?? [:]
      guard project == loadedProject else { return }
      app.loadFiles()
      editing = true
      app.selectedFile = string(result, "path")
      app.notice = "Created " + selected
      await app.refreshGit()
    }
  }
  private func filterFiles() {
    visibleFiles = Set(app.files + app.recoveredFilePaths).sorted().filter {
      search.isEmpty || $0.localizedCaseInsensitiveContains(search)
    }
  }
  private func stash() {
    guard !loading, !loadedProject.isEmpty, !loadedPath.isEmpty, !digest.isEmpty else { return }
    if dirty {
      app.fileDrafts[draftKey] = FileEdit(original: original, digest: digest, text: content)
    } else {
      app.fileDrafts.removeValue(forKey: draftKey)
    }
  }
  private func load() {
    loadGeneration += 1
    guard !selected.isEmpty else {
      loading = false
      loadedPath = ""
      content = ""
      original = ""
      digest = ""
      fileIssue = ""
      return
    }
    let generation = loadGeneration
    let path = selected
    let project = loadedProject
    loading = true
    loadedPath = path
    fileIssue = ""
    conflicted = false
    diskContent = ""
    content = ""
    original = ""
    digest = ""
    let recovered = app.fileDrafts[project + "\n" + path]
    if let recovered {
      original = recovered.original
      digest = recovered.digest
      content = recovered.text
      editing = true
    }
    app.perform {
      defer { if generation == loadGeneration { loading = false } }
      do {
        let result = try await app.engine.call("files.read", ["project": project, "path": path]) as? [String: Any] ?? [:]
        guard generation == loadGeneration, selected == path, loadedProject == project else { return }
        diskContent = string(result, "text")
        if let recovered {
          conflicted = recovered.digest != string(result, "digest")
          if conflicted { fileIssue = "The file changed on disk. Your draft is preserved. Compare, Copy or Save As before discarding it." }
        } else {
          original = string(result, "text")
          digest = string(result, "digest")
          content = original
        }
      } catch {
        guard generation == loadGeneration, selected == path, loadedProject == project else { return }
        conflicted = true
        diskContent = "File unavailable: " + error.localizedDescription
        fileIssue = recovered == nil ? diskContent
          : "The file is unavailable. Your recovered draft is preserved; use Copy or Save As. " + error.localizedDescription
      }
    }
  }
  private func save() {
    let path = selected
    let project = loadedProject
    let text = content
    let revision = digest
    saving = true
    app.perform {
      defer { saving = false }
      do {
        let result = try await app.engine.call(
          "files.write", ["project": project, "path": path, "text": text, "digest": revision])
        as? [String: Any] ?? [:]
        app.fileDrafts.removeValue(forKey: project + "\n" + path)
        app.flushRecovery()
        if selected == path {
          original = text
          digest = string(result, "digest")
          diskContent = text
          fileIssue = ""
        }
        app.notice = "Saved " + path
        await app.refreshGit()
      } catch {
        if selected == path, loadedProject == project {
          fileIssue = "Your draft is preserved. " + error.localizedDescription
          stash()
          app.flushRecovery()
          await readDiskForComparison(project: project, path: path)
        }
      }
    }
  }
  @ViewBuilder private func comparisonColumn(_ title: String, text: String) -> some View {
    VStack(alignment: .leading) {
      Text(title).font(.caption.bold())
      SourceEditor(text: .constant(text), path: loadedPath, editable: false,
        documentID: title + "\n" + loadedPath)
    }.frame(maxWidth: .infinity)
  }
  private func compare() {
    let project = loadedProject
    let path = loadedPath
    app.perform {
      await readDiskForComparison(project: project, path: path)
      guard project == loadedProject, path == loadedPath else { return }
      comparing = true
    }
  }
  private func readDiskForComparison(project: String, path: String) async {
    do {
      let result = try await app.engine.call("files.read", ["project": project, "path": path]) as? [String: Any] ?? [:]
      guard project == loadedProject, path == loadedPath else { return }
      diskContent = string(result, "text")
      conflicted = digest != string(result, "digest")
    } catch {
      guard project == loadedProject, path == loadedPath else { return }
      conflicted = true
      diskContent = "File unavailable: " + error.localizedDescription
    }
  }
  private func saveAs() {
    let panel = NSSavePanel()
    panel.title = "Save a copy of your draft"
    panel.nameFieldStringValue = URL(fileURLWithPath: loadedPath).lastPathComponent + ".recovered"
    guard panel.runModal() == .OK, let url = panel.url else { return }
    let source = URL(fileURLWithPath: string(app.project, "path")).appendingPathComponent(loadedPath)
    guard url.resolvingSymlinksInPath().standardizedFileURL != source.resolvingSymlinksInPath().standardizedFileURL else {
      app.error = "Choose another file. Use Save with a revision check to update the original."
      return
    }
    do {
      try Data(content.utf8).write(to: url, options: .atomic)
      app.notice = "Saved a copy to " + url.path + ". The recovered draft is still available."
    } catch { app.error = error.localizedDescription }
  }
}
struct SettingsView: View {
  @AppStorage("animatedInterface") private var animatedInterface = true
  @AppStorage("colourfulAgentResponses") private var colourfulResponses = true
  @EnvironmentObject var app: Workspace
  var body: some View {
    ScrollView {
      Form {
        Section("Appearance") {
          Toggle("Animate navigation and active agent indicators", isOn: $animatedInterface)
          Text("Animations respect macOS Reduce Motion.").font(.caption).foregroundStyle(.secondary)
          Toggle("SuperQode gradient in agent responses", isOn: $colourfulResponses)
          Text(
            "Code blocks keep readable syntax colours. Increase Contrast uses plain, high-contrast code."
          ).font(.caption).foregroundStyle(.secondary)
          Picker("Theme", selection: $app.theme) {
            Text("Dark").tag("dark")
            Text("Light").tag("light")
            Text("System").tag("system")
          }
        }
        Section("Local engine") {
          LabeledContent("Status", value: app.connected ? "Connected over private pipes" : "Offline")
          LabeledContent("Execution", value: "This Mac")
          Text(
            "Provider requests go directly from the local engine to your configured provider. The app does not upload project data to a SuperQode service."
          ).font(.caption).foregroundStyle(.secondary)
          Text(
            "Connect model stores optional provider keys in macOS Keychain. Desktop preferences contain provider IDs, not secrets. Existing terminal credentials remain supported."
          ).font(.caption).foregroundStyle(.secondary)
        }
        Section {
          Button("Connect…") { app.showConnection = true }.disabled(app.project.isEmpty)
          Button("Save preferences", action: app.savePreferences)
          Button("Open application data") {
            NSWorkspace.shared.open(
              FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask)[0]
                .appendingPathComponent("SuperQode"))
          }
        }
      }.formStyle(.columns).scrollContentBackground(.hidden).padding(12)
    }.background(Color.qPanel)
  }
}
