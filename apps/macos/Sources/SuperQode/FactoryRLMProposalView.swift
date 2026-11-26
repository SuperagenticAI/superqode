import SwiftUI

/// Parsed RLM On-Demand Factory inspection receipt returned by `rlm-architect`.
struct FactoryRLMLineageSnapshot: Equatable {
  struct RecommendedSkill: Identifiable, Equatable {
    let id: String
    let name: String
    let preset: String
    let reason: String
  }

  struct SubcallEntry: Identifiable, Equatable {
    let id: String
    let topic: String
    let ok: Bool
    let inputTokens: Int
    let outputTokens: Int
    let durationMs: Int
    let error: String
  }

  let engine: String
  let mode: String
  let repoFiles: Int
  let repoBytes: Int
  let filesInspected: [String]
  let detectedStacks: [String]
  let detectedTestCommand: String
  let detectedBuildCommand: String
  let sensitiveAreas: [String]
  let recommendedWorkflow: String
  let recommendedSkills: [RecommendedSkill]
  let subcalls: [SubcallEntry]
  let usedCalls: Int
  let maxCalls: Int
  let totalTokens: Int
  let durationMs: Int

  var engineLabel: String {
    engine == "monty-repl" ? "RLM · Monty REPL" : "RLM · Repo Context"
  }

  var modeLabel: String {
    mode == "rlm-live" ? "Live · \(usedCalls)/\(maxCalls) sub-queries" : "Local repo scan"
  }

  var workflowStagesSummary: String {
    switch recommendedWorkflow {
    case "triage-spec-build":
      return "Triage → Conditional Spec (Human Gate) → Implement → Verify (Human Gate)"
    case "fix-and-verify":
      return "Investigate → Implement → Verify (Human Gate)"
    case "build-test-deploy":
      return "Build → Test → Verify & Release Gate"
    default:
      return recommendedWorkflow.isEmpty ? "Tailored multi-stage pipeline" : recommendedWorkflow
    }
  }

  static func parse(proposal: [String: Any]) -> FactoryRLMLineageSnapshot? {
    guard let lineage = proposal["rlm_lineage"] as? [String: Any], !lineage.isEmpty else {
      return nil
    }
    let rawSkills = (proposal["recommended_skills"] as? [[String: Any]])
      ?? (lineage["recommended_skills"] as? [[String: Any]]) ?? []
    let skills = rawSkills.compactMap { row -> RecommendedSkill? in
      let name = row["name"] as? String ?? ""
      guard !name.isEmpty else { return nil }
      let preset = row["preset"] as? String ?? ""
      let reason = row["reason"] as? String ?? ""
      return RecommendedSkill(id: "\(name)-\(preset)", name: name, preset: preset, reason: reason)
    }
    let rawSubcalls = lineage["subcalls"] as? [[String: Any]] ?? []
    let subcalls = rawSubcalls.enumerated().map { idx, row in
      SubcallEntry(
        id: row["id"] as? String ?? "subcall-\(idx + 1)",
        topic: row["topic"] as? String ?? "inspection",
        ok: row["ok"] as? Bool ?? false,
        inputTokens: row["input_tokens"] as? Int ?? 0,
        outputTokens: row["output_tokens"] as? Int ?? 0,
        durationMs: row["duration_ms"] as? Int ?? 0,
        error: row["error"] as? String ?? ""
      )
    }
    let budget = lineage["subcall_budget"] as? [String: Any] ?? [:]
    return FactoryRLMLineageSnapshot(
      engine: lineage["engine"] as? String ?? "rlm-context",
      mode: lineage["mode"] as? String ?? "rlm-local-inspect",
      repoFiles: lineage["repo_files"] as? Int ?? 0,
      repoBytes: lineage["repo_bytes"] as? Int ?? 0,
      filesInspected: lineage["files_inspected"] as? [String] ?? [],
      detectedStacks: lineage["detected_stacks"] as? [String] ?? [],
      detectedTestCommand: lineage["detected_test_command"] as? String ?? "",
      detectedBuildCommand: lineage["detected_build_command"] as? String ?? "",
      sensitiveAreas: lineage["sensitive_areas"] as? [String] ?? [],
      recommendedWorkflow: lineage["recommended_workflow"] as? String ?? "",
      recommendedSkills: skills,
      subcalls: subcalls,
      usedCalls: budget["used_calls"] as? Int ?? 0,
      maxCalls: budget["max_calls"] as? Int ?? 4,
      totalTokens: budget["total_tokens"] as? Int ?? 0,
      durationMs: lineage["duration_ms"] as? Int ?? 0
    )
  }
}

/// Review card for an RLM On-Demand Factory proposal with full inspection provenance.
struct FactoryRLMProposalCard: View {
  let snapshot: FactoryRLMLineageSnapshot
  let assumptions: [String]
  let missingCapabilities: [String]
  let busy: Bool
  let onApply: ([FactoryRLMLineageSnapshot.RecommendedSkill]) -> Void
  let onApplyYamlOnly: () -> Void
  let onDismiss: () -> Void
  var definitionDiff = ""

  @State private var showTrace = false
  @State private var disabledSkillIDs: Set<String> = []

  private var selectedSkills: [FactoryRLMLineageSnapshot.RecommendedSkill] {
    snapshot.recommendedSkills.filter { !disabledSkillIDs.contains($0.id) }
  }

  var body: some View {
    VStack(alignment: .leading, spacing: 12) {
      HStack(spacing: 8) {
        Label("On-Demand Software Factory ready", systemImage: "checkmark.seal.fill")
          .font(.subheadline.weight(.semibold))
          .foregroundStyle(Brand.purple)
        pill(snapshot.engineLabel, color: Brand.purple)
        pill(snapshot.modeLabel, color: snapshot.mode == "rlm-live" ? Brand.pink : Color(red: 0.14, green: 0.62, blue: 0.42))
        Spacer()
        if snapshot.durationMs > 0 {
          Text(String(format: "%.1fs", Double(snapshot.durationMs) / 1000.0))
            .font(.caption.monospacedDigit())
            .foregroundStyle(.secondary)
        }
        Button { onDismiss() } label: {
          Image(systemName: "xmark")
            .font(.caption2)
            .foregroundStyle(.secondary)
        }
        .buttonStyle(.plain)
        .help("Dismiss proposal")
      }

      // Interactive 3-step visual summary of what SuperQode just did
      HStack(spacing: 8) {
        stepBadge("1", "Scanned \(snapshot.repoFiles) files")
        Image(systemName: "arrow.right").font(.caption2).foregroundStyle(.tertiary)
        stepBadge("2", "Detected \(snapshot.detectedStacks.joined(separator: ", "))")
        Image(systemName: "arrow.right").font(.caption2).foregroundStyle(.tertiary)
        stepBadge("3", "Built \(snapshot.recommendedWorkflow)")
      }

      // Clear breakdown of what this factory sets up for the repo
      VStack(alignment: .leading, spacing: 6) {
        HStack(alignment: .firstTextBaseline, spacing: 6) {
          Image(systemName: "person.3.sequence")
            .font(.caption)
            .foregroundStyle(Brand.purple)
          Text("Agents & stages:")
            .font(.caption.weight(.medium))
          Text(snapshot.workflowStagesSummary)
            .font(.caption)
            .foregroundStyle(.secondary)
        }

        if !snapshot.detectedTestCommand.isEmpty {
          HStack(spacing: 6) {
            Image(systemName: "checkmark.shield")
              .font(.caption)
              .foregroundStyle(Color(red: 0.14, green: 0.62, blue: 0.42))
            Text("Regression check:")
              .font(.caption.weight(.medium))
            Text(snapshot.detectedTestCommand)
              .font(.caption.monospaced())
              .padding(.horizontal, 6)
              .padding(.vertical, 2)
              .background(Color.primary.opacity(0.06), in: RoundedRectangle(cornerRadius: 5))
          }
        }

        if !snapshot.sensitiveAreas.isEmpty {
          HStack(spacing: 6) {
            Image(systemName: "shield.lefthalf.filled")
              .font(.caption)
              .foregroundStyle(.orange)
            Text("High-risk paths:")
              .font(.caption.weight(.medium))
            Text(snapshot.sensitiveAreas.prefix(4).joined(separator: ", "))
              .font(.caption.monospaced())
              .foregroundStyle(.secondary)
              .lineLimit(1)
          }
        }
      }

      if !snapshot.recommendedSkills.isEmpty {
        VStack(alignment: .leading, spacing: 6) {
          Text("Choose Factory skills to attach")
            .font(.caption.weight(.semibold))
          ForEach(snapshot.recommendedSkills) { skill in
            let isOn = !disabledSkillIDs.contains(skill.id)
            Toggle(isOn: Binding(
              get: { isOn },
              set: { enabled in
                if enabled { disabledSkillIDs.remove(skill.id) }
                else { disabledSkillIDs.insert(skill.id) }
              }
            )) {
              HStack(alignment: .firstTextBaseline, spacing: 6) {
                Text(skill.preset.isEmpty ? skill.name : "\(skill.name) (\(skill.preset))")
                  .font(.caption.weight(.medium))
                Text("· \(skill.reason)")
                  .font(.caption)
                  .foregroundStyle(.secondary)
                  .lineLimit(2)
              }
            }
            .toggleStyle(.checkbox)
          }
        }
      }

      if !definitionDiff.isEmpty {
        DisclosureGroup("Review proposed definition changes") {
          ScrollView(.horizontal) {
            Text(definitionDiff).font(.system(.caption, design: .monospaced)).textSelection(.enabled)
          }.frame(maxHeight: 220)
        }
      }
      if !assumptions.isEmpty {
        VStack(alignment: .leading, spacing: 3) {
          ForEach(assumptions, id: \.self) { item in
            Text("• \(item)")
              .font(.caption)
              .foregroundStyle(.secondary)
          }
        }
      }

      DisclosureGroup(
        "How SuperQode analyzed this repository (\(snapshot.filesInspected.count) manifests read, \(snapshot.subcalls.count) sub-queries)",
        isExpanded: $showTrace
      ) {
        VStack(alignment: .leading, spacing: 6) {
          if !snapshot.filesInspected.isEmpty {
            Text("Files inspected: " + snapshot.filesInspected.joined(separator: ", "))
              .font(.caption2.monospaced())
              .foregroundStyle(.secondary)
          }
          ForEach(snapshot.subcalls) { call in
            HStack(spacing: 6) {
              Image(systemName: call.ok ? "checkmark.circle.fill" : "exclamationmark.triangle.fill")
                .foregroundStyle(call.ok ? .green : .orange)
                .font(.caption2)
              Text("\(call.id) · \(call.topic)")
                .font(.caption2.weight(.medium))
              if call.inputTokens + call.outputTokens > 0 {
                Text("(\(call.inputTokens + call.outputTokens) tok)")
                  .font(.caption2.monospacedDigit())
                  .foregroundStyle(.secondary)
              }
              if !call.error.isEmpty {
                Text(call.error)
                  .font(.caption2)
                  .foregroundStyle(.orange)
                  .lineLimit(1)
              }
            }
          }
        }
        .padding(.top, 4)
      }
      .font(.caption.weight(.medium))

      HStack(spacing: 10) {
        Button {
          onApply(selectedSkills)
        } label: {
          Label(
            selectedSkills.isEmpty ? "Apply & Edit Factory →" : "Apply, Add \(selectedSkills.count) Skills & Edit Factory →",
            systemImage: "arrow.right.circle.fill"
          )
        }
        .buttonStyle(BrandButtonStyle())
        .disabled(busy)
        .accessibilityIdentifier("factory.rlm.applyWithSkills")

        Button("Open YAML only") {
          onApplyYamlOnly()
        }
        .disabled(busy)
        .accessibilityIdentifier("factory.rlm.applyYamlOnly")
      }

      HStack(alignment: .firstTextBaseline, spacing: 6) {
        Image(systemName: "sparkles")
          .font(.caption2)
          .foregroundStyle(Brand.purple)
        Text("**Coming next — Recursive Software Factories:** dynamically spawn isolated, SuperGauge-verified sub-factories on demand for multi-service and monorepo tasks, governed by your committed `factory.yaml`.")
          .font(.caption2)
          .foregroundStyle(.secondary)
      }
      .padding(.horizontal, 10)
      .padding(.vertical, 7)
      .frame(maxWidth: .infinity, alignment: .leading)
      .background(Brand.purple.opacity(0.06), in: RoundedRectangle(cornerRadius: 8))
    }
    .padding(14)
    .brandSurface()
    .overlay(RoundedRectangle(cornerRadius: 12).strokeBorder(Brand.purple.opacity(0.45), lineWidth: 1.5))
  }

  private func stepBadge(_ number: String, _ label: String) -> some View {
    HStack(spacing: 4) {
      Image(systemName: "checkmark.circle.fill")
        .font(.caption2)
        .foregroundStyle(Color(red: 0.14, green: 0.62, blue: 0.42))
      Text(label)
        .font(.caption2.weight(.medium))
    }
    .padding(.horizontal, 8)
    .padding(.vertical, 3)
    .background(Color.primary.opacity(0.05), in: Capsule())
  }

  private func pill(_ text: String, color: Color) -> some View {
    Text(text)
      .font(.caption2.weight(.semibold))
      .foregroundStyle(color)
      .padding(.horizontal, 7)
      .padding(.vertical, 2)
      .background(color.opacity(0.12), in: Capsule())
  }
}

/// Compact context banner shown on the Definition page right after applying an On-Demand proposal.
struct FactoryOnDemandSummaryBanner: View {
  let snapshot: FactoryRLMLineageSnapshot
  let onViewStages: () -> Void
  let onEditConfig: () -> Void
  let onDismiss: () -> Void

  var body: some View {
    VStack(alignment: .leading, spacing: 8) {
      HStack(spacing: 8) {
        Label("On-Demand Software Factory loaded — edit freely below", systemImage: "checkmark.seal.fill")
          .font(.caption.weight(.semibold))
          .foregroundStyle(Brand.purple)
        Text("· \(snapshot.detectedStacks.joined(separator: ", ")) · \(snapshot.repoFiles) files scanned")
          .font(.caption)
          .foregroundStyle(.secondary)
        Spacer()
        Button { onDismiss() } label: {
          Image(systemName: "xmark")
            .font(.caption2)
            .foregroundStyle(.secondary)
        }
        .buttonStyle(.plain)
        .help("Dismiss summary")
      }
      Text("Pipeline: \(snapshot.workflowStagesSummary) · Check: \(snapshot.detectedTestCommand)")
        .font(.caption)
        .foregroundStyle(.secondary)
        .lineLimit(2)
      HStack(spacing: 10) {
        Button { onViewStages() } label: {
          Label("Inspect stages & agents", systemImage: "point.3.connected.trianglepath.dotted")
        }
        .controlSize(.small)
        Button { onEditConfig() } label: {
          Label("Edit model, budget & skills", systemImage: "slider.horizontal.3")
        }
        .controlSize(.small)
        Spacer()
        Text("Coming next: Recursive Software Factories")
          .font(.caption2)
          .foregroundStyle(Brand.purple.opacity(0.85))
      }
    }
    .padding(.horizontal, 12)
    .padding(.vertical, 10)
    .background(Brand.purple.opacity(0.06), in: RoundedRectangle(cornerRadius: 10))
    .overlay(RoundedRectangle(cornerRadius: 10).strokeBorder(Brand.purple.opacity(0.24), lineWidth: 1))
  }
}
