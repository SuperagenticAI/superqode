import SwiftUI

/// A task becomes a reviewed Super Agent preview.
/// A Python check prints a template in Monty and is never installed into the app.
struct CreatorModeView: View {
  @EnvironmentObject var app: Workspace
  @State private var description = ""
  @State private var draft: [String: Any] = [:]
  @State private var draftedDescription = ""
  @State private var reason = ""
  @State private var savedName = ""
  @State private var montyOutput = ""
  @State private var failure = ""
  @State private var busy = false

  private var panels: [String] { stringList(draft["panels"]) }
  private var warnings: [String] { stringList(draft["warnings"]) }
  private var ready: Bool { !string(draft, "review").isEmpty && description == draftedDescription }
  private var boundRoute: Bool {
    let route = draft["route"] as? [String: Any] ?? [:]
    return !string(route, "provider").isEmpty && !string(route, "model").isEmpty
  }

  var body: some View {
    ScrollView {
      VStack(alignment: .leading, spacing: 18) {
        PageTitle(
          eyebrow: "Super Agent",
          title: "Draft a Super Agent",
          subtitle: "This is a reviewed preview. SuperQode writes a harness definition, a next-prompt note, and a pure-Python check. The check prints a template in Monty. It does not call a model, start a child agent, or install anything. Enabling the harness is a separate step."
        )
        Text(
          "The draft keeps Agent Space, Review, Files, Terminal, and Tools. The generated harness uses the builtin runtime, ordinary coding tools, and Ask. Recursion is not connected. Gauges, factory, and RLM stay in Tools."
        ).font(.callout).foregroundStyle(.secondary)
        TextEditor(text: $description)
          .font(.system(size: 14))
          .frame(minHeight: 120, maxHeight: 180)
          .outlinedSurface(radius: 8)
          .onChange(of: description) { _, value in
            if value != draftedDescription {
              draft = [:]
              savedName = ""
              montyOutput = ""
            }
          }
        HStack {
          Button(busy ? "Drafting…" : "Draft Super Agent") { propose() }
            .buttonStyle(BrandButtonStyle())
            .disabled(busy || description.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
          Spacer()
          Text("\(description.count)/4000").font(.caption.monospaced()).foregroundStyle(.secondary)
        }
        if !failure.isEmpty {
          Text(failure).foregroundStyle(.orange).textSelection(.enabled)
        }
        if ready {
          if !warnings.isEmpty {
            Text(warnings.joined(separator: "\n")).font(.caption).foregroundStyle(.orange).textSelection(.enabled)
          }
          Text("Layout · " + panels.map { Sections.title(for: $0) }.joined(separator: " · "))
            .font(.system(size: 12, design: .monospaced))
          reviewBlock("Harness definition", string(draft, "yaml"))
          reviewBlock("Who writes the next prompt", string(draft, "recursion"))
          reviewBlock("Monty check", string(draft, "plugin"))
          reviewBlock("Skill note", string(draft, "skill"))
          reviewBlock("Work program", string(draft, "program"))
          TextField("Why save this revision?", text: $reason).textFieldStyle(.roundedBorder)
          HStack(spacing: 12) {
            Button("Save reviewed draft") { save() }
              .disabled(busy || reason.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
            Button("Run Monty check") { runMonty() }
              .disabled(busy || savedName.isEmpty)
            Button("Enable saved revision…") { enable() }
              .disabled(busy || savedName.isEmpty || !boundRoute)
          }
          if !montyOutput.isEmpty {
            Text("Monty output. The template was not installed and did not call a model.").font(.caption).foregroundStyle(.secondary)
            CodeBlock(text: montyOutput).frame(height: 120)
          }
          Text(savedName.isEmpty
            ? "Saving writes the reviewed preview under .superqode/creator. The revision stays off. The Python check runs only after you save it, and only inside Monty."
            : boundRoute
              ? "Saved \(savedName). It is a preview: builtin tools, recursion off, and the Monty check prints a template. It is not enabled and the check is not installed."
              : "Saved \(savedName). Choose a provider and model, then draft again, before enabling this preview."
          ).font(.caption).foregroundStyle(.secondary)
        }
      }.padding(28).frame(maxWidth: .infinity, alignment: .topLeading)
    }.defaultScrollAnchor(.top)
  }

  private func reviewBlock(_ title: String, _ text: String) -> some View {
    DisclosureGroup(title) {
      CodeBlock(text: text).frame(height: 180)
    }.font(.callout)
  }

  private func propose() {
    let text = description.trimmingCharacters(in: .whitespacesAndNewlines)
    guard !text.isEmpty, text.count <= 4000 else {
      failure = "Describe the repository workflow in up to 4,000 characters"
      return
    }
    let project = app.projectID
    busy = true
    failure = ""
    Task {
      defer { busy = false }
      do {
        var request: [String: Any] = ["project": project, "description": text]
        if let route = app.reviewedModelRoute { request["route"] = route }
        let result = try await app.engine.call(
          "superagent.propose", request) as? [String: Any] ?? [:]
        guard app.projectID == project, description.trimmingCharacters(in: .whitespacesAndNewlines) == text else { return }
        draft = result
        draftedDescription = description
        savedName = ""
      } catch {
        failure = error.localizedDescription
      }
    }
  }

  private func save() {
    guard ready else { return }
    let project = app.projectID
    let snapshot = draft
    let note = reason.trimmingCharacters(in: .whitespacesAndNewlines)
    busy = true
    failure = ""
    Task {
      defer { busy = false }
      do {
        let saved = try await app.engine.call(
          "superagent.save",
          [
            "project": project,
            "name": string(snapshot, "name"),
            "review": string(snapshot, "review"),
            "digest": string(snapshot, "digest"),
            "expected_file_digest": string(snapshot, "expected_file_digest"),
            "reason": note,
            "skill": string(snapshot, "skill"),
            "program": string(snapshot, "program"),
            "skill_digest": string(snapshot, "skill_digest"),
            "program_digest": string(snapshot, "program_digest"),
            "recursion": string(snapshot, "recursion"),
            "recursion_digest": string(snapshot, "recursion_digest"),
            "plugin": string(snapshot, "plugin"),
            "plugin_digest": string(snapshot, "plugin_digest"),
            "panels": stringList(snapshot["panels"]),
            "layout_digest": string(snapshot, "layout_digest"),
          ]) as? [String: Any] ?? [:]
        guard app.projectID == project else { return }
        guard saved["enabled"] as? Bool == false else {
          failure = "The draft was not saved as a disabled revision."
          return
        }
        savedName = string(saved, "id", string(snapshot, "name"))
        montyOutput = ""
        await app.loadRepositoryLayout()
        app.notice = "Super Agent draft saved. It is not enabled, and its check is not installed."
      } catch {
        failure = error.localizedDescription
      }
    }
  }

  private func runMonty() {
    let project = app.projectID
    let name = savedName
    let digest = string(draft, "plugin_digest")
    guard !name.isEmpty, !digest.isEmpty else { return }
    busy = true
    failure = ""
    Task {
      defer { busy = false }
      do {
        let result = try await app.engine.call(
          "superagent.monty",
          ["project": project, "name": name, "plugin_digest": digest]) as? [String: Any] ?? [:]
        guard app.projectID == project else { return }
        guard result["installed"] as? Bool == false, string(result, "sandbox") == "monty" else {
          failure = "The check did not stay inside Monty."
          return
        }
        montyOutput = string(result, "output")
        app.notice = "Monty ran the check. It was not installed."
      } catch {
        failure = error.localizedDescription
      }
    }
  }

  private func enable() {
    let project = app.projectID
    let name = savedName
    guard !name.isEmpty else { return }
    busy = true
    failure = ""
    Task {
      defer { busy = false }
      do {
        let rows = try await app.engine.call(
          "studio.revisions", ["project": project, "name": name]) as? [[String: Any]] ?? []
        guard let revision = rows.first(where: { $0["intact"] as? Bool == true }) else {
          failure = "Save a revision before enabling it."
          return
        }
        let result = try await app.engine.call(
          "studio.use",
          ["project": project, "name": name, "revision": string(revision, "id")]) as? [String: Any] ?? [:]
        guard app.projectID == project, !app.anyActive else { return }
        let definitions = try await app.engine.call("harnesses.list", ["project": project]) as? [[String: Any]] ?? []
        app.harnesses = definitions + app.harnesses.filter { !string($0, "desktop_kind").isEmpty }
        app.chooseHarness(string(result, "reference"))
        let route = result["route"] as? [String: Any] ?? [:]
        if !string(route, "provider").isEmpty && !string(route, "model").isEmpty {
          app.chooseModelRoute(string(route, "provider"), string(route, "model"))
        }
        await app.loadRepositoryLayout()
        app.notice = "Super Agent selected. It is not installed into the app, and no prompt has been sent."
        app.section = "Workspace"
      } catch {
        failure = error.localizedDescription
      }
    }
  }
}

private func stringList(_ value: Any?) -> [String] {
  if let rows = value as? [String] { return rows }
  return (value as? [Any])?.compactMap { $0 as? String } ?? []
}
