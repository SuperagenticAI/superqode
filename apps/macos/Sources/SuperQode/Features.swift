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
          Button("Open result…", action: importResult)
        }
        GroupBox {
          VStack(alignment: .leading, spacing: 18) {
            RouteControls(allowACP: false)
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
              HStack {
                TextField("Optional candidate HarnessSpec path", text: $variant).textFieldStyle(
                  .roundedBorder)
                Button("Choose…") { chooseFile { variant = $0 } }
              }
              Toggle("Live evaluation · run harnesses and allow model charges", isOn: $live)
              Text(
                live
                  ? "Live evaluations execute suite tasks using the selected route."
                  : "Setup check validates the configuration and skips execution. It does not measure coding quality."
              ).font(.caption).foregroundStyle(.secondary)
            }
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
                suite.isEmpty || app.model.isEmpty || app.busy || app.anyActive || app.isACP
                  || (optimize
                    && (!live || reflection.isEmpty || optimizer.isEmpty
                      || app.capabilities["omni"] as? Bool != true))
              )
            }
          }.padding(14)
        }
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
  }
  var optimizationResult: some View {
    VStack(alignment: .leading, spacing: 16) {
      HStack {
        Metric(label: "BASELINE SCORE", value: String(describing: result["baseline_score"] ?? "—"))
        Metric(label: "CANDIDATE SCORE", value: String(describing: result["best_score"] ?? "—"))
        Pill(
          title: result["accepted"] as? Bool == true ? "GATE PASSED" : "REVIEW REQUIRED",
          color: result["accepted"] as? Bool == true ? .green : .orange)
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
    } else if !variant.isEmpty {
      params["variant"] = variant
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
            Text(
              String(describing: variant["passed"] ?? 0) + " passed · "
                + String(describing: variant["failed"] ?? 0) + " failed · "
                + String(describing: variant["skipped"] ?? 0) + " skipped · "
                + ((variant["cost_usd"] as? Double).flatMap {
                  $0.isFinite && $0 >= 0 ? String(format: "$%.4f", $0) : nil
                } ?? "Cost unknown")
            ).font(.caption.monospaced()).foregroundStyle(.secondary)
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
}
struct FilesView: View {
  @EnvironmentObject var app: Workspace
  @State private var search = ""
  @State private var visibleFiles: [String] = []
  @State private var creating = false
  @State private var newPath = ""
  @State private var selected = ""
  @State private var content = ""
  @State private var original = ""
  @State private var digest = ""
  @State private var loadedProject = ""
  @State private var editing = false
  @State private var loading = false
  @State private var saving = false
  @State private var loadGeneration = 0
  private var dirty: Bool { content != original }
  private var draftKey: String { loadedProject + "\n" + selected }
  var body: some View {
    VStack(alignment: .leading, spacing: 20) {
      PageTitle(
        eyebrow: "Stay close to the code", title: "Project files",
        subtitle:
          "Read and edit project source files here. Save with a revision check, then review the diff."
      )
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
            id: \.self, selection: $selected
          ) { Text($0).font(.system(size: 11, design: .monospaced)).tag($0) }
            .scrollContentBackground(.hidden).background(Color.qPanel).disabled(saving)
        }.frame(minWidth: 220, idealWidth: 300, maxWidth: 400)
        VStack(alignment: .leading, spacing: 12) {
          HStack {
            Text(selected.isEmpty ? "Select a file" : selected).font(.caption.monospaced())
              .lineLimit(1)
            if dirty { Pill(title: "UNSAVED", color: .orange) }
            Spacer()
            Toggle("Edit", isOn: $editing).toggleStyle(.checkbox).disabled(selected.isEmpty)
            Button("Reload") {
              if !dirty
                || app.confirm(
                  "Discard unsaved edits?",
                  "Reload this file from disk and discard its in-memory draft.", button: "Reload")
              {
                app.fileDrafts.removeValue(forKey: draftKey)
                load()
              }
            }.disabled(selected.isEmpty || loading || saving)
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
            Button("Save", action: save).keyboardShortcut("s").disabled(
              !dirty || digest.isEmpty || loading || saving || app.anyActive)
            Button("Open in editor") {
              NSWorkspace.shared.open(
                URL(fileURLWithPath: string(app.project, "path")).appendingPathComponent(selected))
            }.disabled(selected.isEmpty)
          }
          SourceEditor(text: $content, path: selected, editable: editing, documentID: loadedProject + "\n" + selected)
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
    .onChange(of: selected) { _, _ in load() }
    .onChange(of: content) { _, _ in stash() }
    .onDisappear { stash(); loadGeneration += 1 }
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
      selected = string(result, "path")
      app.notice = "Created " + selected
      await app.refreshGit()
    }
  }
  private func filterFiles() {
    visibleFiles = app.files.filter { search.isEmpty || $0.localizedCaseInsensitiveContains(search) }
  }
  private func stash() {
    guard !loadedProject.isEmpty, !selected.isEmpty, !digest.isEmpty else { return }
    if dirty {
      app.fileDrafts[draftKey] = FileEdit(original: original, digest: digest, text: content)
    } else {
      app.fileDrafts.removeValue(forKey: draftKey)
    }
  }
  private func load() {
    loadGeneration += 1
    guard !selected.isEmpty else { loading = false; return }
    let generation = loadGeneration
    let path = selected
    let project = loadedProject
    loading = true
    content = ""
    original = ""
    digest = ""
    app.perform {
      defer { if generation == loadGeneration { loading = false } }
      do {
        let result = try await app.engine.call("files.read", ["project": project, "path": path]) as? [String: Any] ?? [:]
        guard generation == loadGeneration, selected == path, loadedProject == project else { return }
        if let draft = app.fileDrafts[project + "\n" + path] {
          original = draft.original
          digest = draft.digest
          content = draft.text
          editing = true
        } else {
          original = string(result, "text")
          digest = string(result, "digest")
          content = original
        }
      } catch {
        if generation == loadGeneration, selected == path { app.error = error.localizedDescription }
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
      let result =
        try await app.engine.call(
          "files.write", ["project": project, "path": path, "text": text, "digest": revision])
        as? [String: Any] ?? [:]
      app.fileDrafts.removeValue(forKey: project + "\n" + path)
      if selected == path {
        original = text
        digest = string(result, "digest")
      }
      app.notice = "Saved " + path
      await app.refreshGit()
    }
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
