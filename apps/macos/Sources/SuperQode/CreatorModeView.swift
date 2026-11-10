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
  private var trimmedDescription: String {
    description.trimmingCharacters(in: .whitespacesAndNewlines)
  }
  private var descriptionTooLong: Bool { trimmedDescription.count > 4000 }
  private var guideStep: Int {
    SuperAgentGuide.current(
      hasProject: !app.projectID.isEmpty,
      hasDescription: !trimmedDescription.isEmpty,
      reviewed: ready,
      saved: !savedName.isEmpty,
      checked: !montyOutput.isEmpty)
  }

  var body: some View {
    ScrollView {
      VStack(alignment: .leading, spacing: 18) {
        PageTitle(
          eyebrow: "Super Agent",
          title: "Draft a Super Agent",
          subtitle: "Describe the job, review what SuperQode writes, then turn the harness on when you want it."
        )
        howTo
        Button("What is Super Agent, and how is DeepSeek Harness different?") {
          app.learningTopic = LearningTopics.superAgent
          app.showLearningGuide = true
        }.buttonStyle(.link)
        Text(SuperAgentGuide.guidance(step: guideStep, canEnable: boundRoute))
          .font(.callout).foregroundStyle(.secondary)
          .fixedSize(horizontal: false, vertical: true)
          .accessibilityAddTraits(.updatesFrequently)
        Text("What should this agent do?").font(.headline)
        Text("Up to 4,000 characters. For example: review this repository and suggest one small fix. Do not edit files until I say so.")
          .font(.callout).foregroundStyle(.secondary)
        TextEditor(text: $description)
          .font(.system(size: 14))
          .frame(minHeight: 120, maxHeight: 180)
          .outlinedSurface(radius: 8)
          .accessibilityLabel("What should this agent do?")
          .overlay(alignment: .topLeading) {
            if description.isEmpty {
              Text("Describe the job for this repository.")
                .font(.system(size: 14)).foregroundStyle(.tertiary)
                .padding(.top, 8).padding(.leading, 5)
                .allowsHitTesting(false)
            }
          }
          .onChange(of: description) { _, value in
            if value != draftedDescription {
              draft = [:]
              savedName = ""
              montyOutput = ""
            }
          }
        HStack {
          if app.projectID.isEmpty {
            Button("Open project…", action: app.chooseProject)
              .buttonStyle(BrandButtonStyle())
              .disabled(!app.connected || app.openingProject)
          }
          Button(busy ? "Drafting…" : "Draft Super Agent") { propose() }
            .buttonStyle(BrandButtonStyle())
            .disabled(busy || app.projectID.isEmpty || trimmedDescription.isEmpty || descriptionTooLong)
            .help(app.projectID.isEmpty
              ? "Open a project first. The draft is saved in that repository."
              : "Prepares a review from this description. Nothing is saved or turned on.")
          Spacer()
          Text("\(description.count)/4000").font(.caption.monospaced())
            .foregroundStyle(descriptionTooLong ? Color.orange : Color.secondary)
        }
        if app.projectID.isEmpty {
          Text("Open a project first. Draft stays off until a repository is open.")
            .font(.caption).foregroundStyle(.secondary)
        }
        if descriptionTooLong {
          Text("Keep the description to 4,000 characters.").font(.caption).foregroundStyle(.orange)
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
          if !boundRoute {
            Text("No provider or model is on this draft. You can still save it and run the Monty check. To enable it, choose a provider and model in Agent Space, then draft again.")
              .font(.callout).foregroundStyle(.secondary)
          }
          TextField("Why save this revision?", text: $reason).textFieldStyle(.roundedBorder)
            .help("Required. This note is stored with the saved revision. Saving does not turn the harness on.")
          HStack(spacing: 12) {
            Button("Save reviewed draft") { save() }
              .disabled(busy || reason.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty)
              .help("Writes the review under .superqode/creator. The harness stays off until you enable it.")
            Button("Run Monty check") { runMonty() }
              .disabled(busy || savedName.isEmpty)
              .help("Runs the saved Python check inside Monty. It prints a template, does not call a model, and is not installed. Save the draft first.")
            Button("Enable saved revision…") { enable() }
              .disabled(busy || savedName.isEmpty || !boundRoute)
              .help(boundRoute
                ? "Selects this harness in Agent Space. It does not send a prompt. You still type a request and press Send."
                : "Choose a provider and model in Agent Space, then draft again, before this is available.")
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
      }.padding(28).frame(maxWidth: 760, alignment: .topLeading)
    }.defaultScrollAnchor(.top)
  }

  private var howTo: some View {
    VStack(alignment: .leading, spacing: 14) {
      ForEach(Array(SuperAgentGuide.steps.enumerated()), id: \.offset) { index, step in
        let number = index + 1
        let done = number < guideStep
        HStack(alignment: .top, spacing: 12) {
          ZStack {
            Circle().fill(done ? Color.green.opacity(0.12) : number == guideStep ? Brand.purple.opacity(0.14) : Color.primary.opacity(0.06))
            if done {
              Image(systemName: "checkmark").foregroundStyle(.green)
            } else {
              Text(String(number)).foregroundStyle(number == guideStep ? Color.primary : Color.secondary)
            }
          }.font(.system(size: 12, weight: .semibold)).frame(width: 28, height: 28)
          VStack(alignment: .leading, spacing: 3) {
            Text(step.title).font(.headline)
              .foregroundStyle(number > guideStep ? Color.secondary : Color.primary)
            Text(step.detail).font(.callout).foregroundStyle(.secondary)
              .fixedSize(horizontal: false, vertical: true)
          }
        }
        .accessibilityElement(children: .combine)
        .accessibilityLabel("Step \(number). \(step.title). \(step.detail)")
        .accessibilityAddTraits(number == guideStep ? .isSelected : [])
      }
      Text("Drafting does not install a plugin, call a model, or send a prompt. The harness uses ordinary coding tools and Ask. Recursion stays off. Agent Space, Review, Files, Terminal, and Tools stay. Gauges, factory, and RLM stay in Tools.")
        .font(.caption).foregroundStyle(.secondary)
        .fixedSize(horizontal: false, vertical: true)
    }.padding(16).brandSurface()
  }

  private func reviewBlock(_ title: String, _ text: String) -> some View {
    DisclosureGroup(title) {
      CodeBlock(text: text).frame(height: 180)
    }.font(.callout)
  }

  private func propose() {
    let text = trimmedDescription
    guard !app.projectID.isEmpty else {
      failure = "Open a project first. The draft is saved in that repository."
      return
    }
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

/// The Super Agent page steps. Draft still only prepares a review.
enum SuperAgentGuide {
  struct Step: Equatable {
    var title: String
    var detail: String
  }

  static let steps: [Step] = [
    Step(
      title: "Open a project",
      detail: "The draft is saved in that repository."),
    Step(
      title: "Describe the job",
      detail: "Say what this agent should do. The box stays empty until you type."),
    Step(
      title: "Press Draft Super Agent",
      detail: "This prepares a review only. Nothing is saved or turned on. Changing the text clears the review."),
    Step(
      title: "Read the five sections, then save",
      detail: "Open the harness, the next-prompt note, the Monty check, the skill note, and the work program. Write why, then press Save reviewed draft. It stays off under .superqode/creator."),
    Step(
      title: "Run the Monty check",
      detail: "Optional, and only after you save. It prints a template. It does not call a model and is not installed. If Monty is missing, the check is refused and is not run on this Mac."),
    Step(
      title: "Enable the saved revision",
      detail: "Enable needs a provider and model already on the draft. If you had not chosen one, pick them in Agent Space and draft again. Enable selects the harness there. You still type a request and press Send."),
  ]

  static func current(hasProject: Bool, hasDescription: Bool, reviewed: Bool, saved: Bool, checked: Bool) -> Int {
    if !hasProject { return 1 }
    if !hasDescription { return 2 }
    if !reviewed { return 3 }
    if !saved { return 4 }
    if !checked { return 5 }
    return 6
  }

  static func guidance(step: Int, canEnable: Bool) -> String {
    switch step {
    case 1:
      "Open a project first. The draft is saved in that repository."
    case 2:
      "Describe the job, then press Draft Super Agent."
    case 3:
      "Press Draft Super Agent. That only prepares a review. Nothing is saved or turned on."
    case 4:
      "Read the five sections. Write why you are saving, then press Save reviewed draft."
    case 5:
      canEnable
        ? "Saved and still off. Run the Monty check if you want, then press Enable. Enable opens Agent Space and does not send a prompt."
        : "Saved and still off. Run the Monty check if you want. To enable it, choose a provider and model in Agent Space, then draft again."
    default:
      canEnable
        ? "The check printed a template and was not installed. Press Enable when you want this harness in Agent Space. You still type a request and press Send."
        : "The check printed a template and was not installed. Choose a provider and model in Agent Space, then draft again, before Enable is available."
    }
  }
}

private func stringList(_ value: Any?) -> [String] {
  if let rows = value as? [String] { return rows }
  return (value as? [Any])?.compactMap { $0 as? String } ?? []
}
