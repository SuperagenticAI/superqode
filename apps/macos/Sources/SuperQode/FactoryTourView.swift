import SwiftUI

/// Collapsible contextual progress strip that shows what just finished and what to do next,
/// without altering Factory Studio's 5-group layout.
struct FactoryNextStepStrip: View {
  let setup: FactorySetupState
  let controlsHaveChanges: Bool
  let idle: Bool
  let onPrimaryAction: () -> Void
  let onOpenTour: () -> Void
  let onHide: () -> Void
  @Environment(\.colorSchemeContrast) private var contrast

  var body: some View {
    VStack(alignment: .leading, spacing: 8) {
      HStack(alignment: .center, spacing: 8) {
        HStack(spacing: 5) {
          ForEach(setup.milestones) { item in
            let isCurrent = item.number - 1 == setup.guidedStepIndex
            HStack(spacing: 4) {
              Image(systemName: item.completed ? "checkmark.circle.fill" : isCurrent ? "circle.inset.filled" : "circle")
                .font(.system(size: 10, weight: .semibold))
                .foregroundStyle(
                  item.completed
                    ? Color(red: 0.14, green: 0.64, blue: 0.42)
                    : isCurrent ? Brand.purple : Color.secondary.opacity(0.6)
                )
              Text(item.title)
                .font(.system(size: 10.5, weight: isCurrent ? .semibold : .regular))
                .foregroundStyle(isCurrent ? Color.primary : Color.secondary)
                .lineLimit(1)
            }
            if item.number < setup.milestones.count {
              Image(systemName: "chevron.right")
                .font(.system(size: 8, weight: .semibold))
                .foregroundStyle(.tertiary)
            }
          }
        }
        Spacer(minLength: 6)
        Button("Factory tour") { onOpenTour() }
          .buttonStyle(.link)
          .font(.caption2)
        Button { onHide() } label: {
          Image(systemName: "xmark")
            .font(.system(size: 9.5, weight: .semibold))
            .foregroundStyle(.secondary)
        }
        .buttonStyle(.plain)
        .help("Hide Next-Step guide (reopen anytime with the Guide button)")
        .accessibilityLabel("Hide next-step guide")
      }

      HStack(alignment: .center, spacing: 10) {
        VStack(alignment: .leading, spacing: 2) {
          HStack(spacing: 6) {
            Text(controlsHaveChanges ? "Configuration edited" : setup.completedBadgeText)
              .font(.caption2.weight(.semibold))
              .foregroundStyle(
                controlsHaveChanges
                  ? Brand.orange
                  : setup.hasDraft ? Color(red: 0.14, green: 0.64, blue: 0.42) : Brand.purple
              )
              .padding(.horizontal, 7)
              .padding(.vertical, 2)
              .background(
                (controlsHaveChanges
                  ? Brand.orange
                  : setup.hasDraft ? Color(red: 0.14, green: 0.64, blue: 0.42) : Brand.purple
                ).opacity(0.12),
                in: Capsule()
              )
            Text(controlsHaveChanges ? "Apply your configuration changes" : setup.nextTitle)
              .font(.caption.weight(.semibold))
              .lineLimit(1)
          }
          Text(
            controlsHaveChanges
              ? "Click Apply controls to draft on Configuration, then save your revision."
              : setup.nextDetail
          )
          .font(.caption)
          .foregroundStyle(.secondary)
          .lineLimit(2)
        }
        Spacer(minLength: 8)
        Button(controlsHaveChanges ? "Open Configuration →" : setup.nextActionTitle) {
          onPrimaryAction()
        }
        .buttonStyle(BrandButtonStyle())
        .controlSize(.small)
        .disabled(!idle && !controlsHaveChanges)
        .accessibilityIdentifier("factory.guide.nextAction")
      }
    }
    .padding(.horizontal, 12)
    .padding(.vertical, 9)
    .background(Color.qPanel, in: RoundedRectangle(cornerRadius: 11, style: .continuous))
    .overlay(
      RoundedRectangle(cornerRadius: 11, style: .continuous)
        .strokeBorder(
          contrast == .increased ? Color.primary.opacity(0.35) : Brand.purple.opacity(0.22),
          lineWidth: 1
        )
        .allowsHitTesting(false)
    )
  }
}

/// Standalone interactive 5-slide walkthrough for learning and demoing how SuperQode Software
/// Factory works — complete with live visual previews, interactive triage simulation,
/// keyboard arrow navigation, and optional auto-play demo mode.
struct FactoryTourSheet: View {
  var onJumpToPage: ((String) -> Void)? = nil
  var onStartStarter: ((String) -> Void)? = nil
  @Environment(\.dismiss) private var dismiss
  @Environment(\.colorScheme) private var scheme
  @State private var index = 0
  @State private var autoPlay = false
  @State private var demoNeedsSpec = true

  private struct Slide: Identifiable {
    let id: Int
    let unit: String
    let title: String
    let subtitle: String
    let symbol: String
    let tint: Color
    let bullets: [(String, String)]
    let callout: String
    let targetTab: String
    let targetTitle: String
  }

  private static let slides: [Slide] = [
    Slide(
      id: 0,
      unit: "Unit 1 · Getting Started",
      title: "From ad-hoc prompts to a Software Factory",
      subtitle: "A Software Factory turns repeatable engineering work into a versioned, staged workflow you can measure, trust, and improve over time.",
      symbol: "building.2.crop.circle.fill",
      tint: Brand.purple,
      bullets: [
        ("Defined as code", "Your stages, checks, skills, and permissions live in .superqode/factory.yaml so the whole team can review and roll back changes."),
        ("Isolated & local-first", "Runs on your Mac with any model or agent you already use — Antigravity ACP, Alibaba Token Plan, Codex, Gemini, or local Ollama/MLX."),
        ("Zero surprise runs", "Drafting, checking, and saving a factory never calls a model or edits your repo until you explicitly start a trial."),
      ],
      callout: "Build → Test → Verify → Improve: start with one small workflow, then layer gates, checks, and self-improvement as trust grows.",
      targetTab: "Stack",
      targetTitle: "Describe"
    ),
    Slide(
      id: 1,
      unit: "Unit 2 · Human Judgment",
      title: "Avoid the \"slop cannon\" with Triage & Two Gates",
      subtitle: "Pushing ambiguous issues straight to a coding agent produces PRs nobody wants to review. Put human judgment where it matters most.",
      symbol: "arrow.triangle.branch",
      tint: Brand.orange,
      bullets: [
        ("Gate 1 · Spec sign-off", "The Triage, spec & build starter routes ambiguous features through a Spec stage that asks clarifying questions and waits for your approval before coding."),
        ("Fast path for clear bugs", "Small, well-scoped fixes skip Spec automatically and go straight to Implement and Verify."),
        ("Gate 2 · Ship approval", "Every finished run waits for your review with diffs, SuperGauge verdicts, and Touch ID release signing."),
      ],
      callout: "Toggle the live preview above to see how conditional routing skips Spec for clear bugs and pauses for human judgment on ambiguous features.",
      targetTab: "Workflow",
      targetTitle: "Workflow"
    ),
    Slide(
      id: 2,
      unit: "Unit 2 · Protect & Skills",
      title: "Attach reusable skills & protected checks",
      subtitle: "Codify how your team verifies work and mitigates risk so agents follow the same playbook on every run.",
      symbol: "checkmark.shield.fill",
      tint: Color(red: 0.14, green: 0.64, blue: 0.42),
      bullets: [
        ("Merge Risk skill", "Teaches agents to self-check Alignment, Impact, Verification, Rollback cost, and Error detection before handing off a PR."),
        ("UI Verification skill", "Guides agents to launch your app, walk the changed user flow, save screenshots to .superqode/factory-proof/, and record reusable Gotchas."),
        ("Protected acceptance checks", "Hidden Python probes run inside an OS sandbox so workers cannot game or modify their own evaluator."),
      ],
      callout: "Add built-in merge-risk and ui-verification skills in one click from Build → Configuration.",
      targetTab: "Configuration",
      targetTitle: "Configuration"
    ),
    Slide(
      id: 3,
      unit: "Unit 3 · Verify & Review",
      title: "Inspect SuperGauge, Merge Risk & Visual Proof",
      subtitle: "Review completed trials at a glance without hunting through raw logs or pulling every branch locally first.",
      symbol: "gauge.with.dots.needle.67percent",
      tint: Brand.pink,
      bullets: [
        ("SuperGauge verdict", "Deterministic SHIP / HOLD / REJECT score from sandboxed probes plus optional advisory model judges."),
        ("5-Dimension Merge Risk", "Advisory Low / Medium / High badge across Alignment, Impact, Verification, Rollback cost, and Error detection."),
        ("Visual Proof & PR Handoff", "Preview captured screenshots right in Changes & Checks and copy a complete Markdown PR summary in one click."),
      ],
      callout: "Applying an approved candidate touches your working tree only — it never commits, pushes, or deploys automatically.",
      targetTab: "Runs",
      targetTitle: "Single trial"
    ),
    Slide(
      id: 4,
      unit: "Unit 3 · Measure & Improve",
      title: "Turn real runs into a self-improving loop",
      subtitle: "Once your first trials work, measure performance on real tasks and let optimizers systematically upgrade your factory.",
      symbol: "sparkles",
      tint: Brand.purple,
      bullets: [
        ("Trial Suites (Benchmarks)", "Replay historical tasks to compare models (for example qwen4-max vs. gemini-4-neon), pass rates, and cost."),
        ("4 Built-in Optimizers", "Run Native, GEPA, MetaHarness, or Omni improvement loops to propose diffed skill and workflow upgrades verified on held-out checks."),
        ("Operations & Portable Export", "Configure schedules/triggers in Operations or export a standalone, vendor-neutral package to your own CI or host."),
      ],
      callout: "Ready to build? Pick a starter below to load your first draft — no model call happens until you start a trial.",
      targetTab: "Improve",
      targetTitle: "Set up experiment"
    ),
  ]

  private var slide: Slide { Self.slides[index] }

  var body: some View {
    VStack(spacing: 0) {
      HStack(spacing: 10) {
        FactoryStudioEmblem(size: 24)
        VStack(alignment: .leading, spacing: 1) {
          Text("Software Factory Tour")
            .font(.headline.weight(.bold))
            .foregroundStyle(Brand.wordmarkGradient(scheme))
          Text("Interactive walkthrough · \(index + 1) of \(Self.slides.count)")
            .font(.caption)
            .foregroundStyle(.secondary)
        }
        Spacer()
        Button {
          autoPlay.toggle()
        } label: {
          Label(autoPlay ? "Pause demo" : "Auto-play", systemImage: autoPlay ? "pause.fill" : "play.fill")
        }
        .controlSize(.small)
        .help("Automatically advance slides every 5 seconds for hands-free demos")
        Button("Close") { dismiss() }
          .keyboardShortcut(.escape, modifiers: [])
      }
      .padding(.horizontal, 22)
      .padding(.vertical, 14)

      Divider()

      ScrollView {
        VStack(alignment: .leading, spacing: 16) {
          HStack(spacing: 12) {
            ZStack {
              RoundedRectangle(cornerRadius: 12, style: .continuous)
                .fill(slide.tint.opacity(0.14))
              Image(systemName: slide.symbol)
                .font(.system(size: 22, weight: .semibold))
                .foregroundStyle(slide.tint)
            }
            .frame(width: 48, height: 48)

            VStack(alignment: .leading, spacing: 3) {
              Text(slide.unit.uppercased())
                .font(.system(size: 10, weight: .bold, design: .monospaced))
                .foregroundStyle(slide.tint)
              Text(slide.title)
                .font(.title3.weight(.semibold))
            }
          }

          Text(slide.subtitle)
            .font(.callout)
            .foregroundStyle(.secondary)
            .fixedSize(horizontal: false, vertical: true)

          slideVisualPreview

          VStack(alignment: .leading, spacing: 8) {
            ForEach(Array(slide.bullets.enumerated()), id: \.offset) { idx, item in
              HStack(alignment: .top, spacing: 10) {
                Text("\(idx + 1)")
                  .font(.caption2.weight(.bold).monospacedDigit())
                  .foregroundStyle(.white)
                  .frame(width: 20, height: 20)
                  .background(slide.tint, in: Circle())
                  .padding(.top, 1)
                VStack(alignment: .leading, spacing: 2) {
                  Text(item.0).font(.subheadline.weight(.semibold))
                  Text(item.1)
                    .font(.caption)
                    .foregroundStyle(.secondary)
                    .fixedSize(horizontal: false, vertical: true)
                }
              }
              .padding(10)
              .frame(maxWidth: .infinity, alignment: .leading)
              .brandSurface(radius: 10)
            }
          }

          HStack(alignment: .top, spacing: 8) {
            Image(systemName: "lightbulb.fill")
              .font(.caption)
              .foregroundStyle(Brand.orange)
              .padding(.top, 1)
            Text(slide.callout)
              .font(.caption)
              .foregroundStyle(.secondary)
              .fixedSize(horizontal: false, vertical: true)
          }
          .padding(10)
          .frame(maxWidth: .infinity, alignment: .leading)
          .background(Brand.orange.opacity(0.08), in: RoundedRectangle(cornerRadius: 10, style: .continuous))
        }
        .padding(22)
      }

      Divider()

      HStack(spacing: 10) {
        HStack(spacing: 6) {
          ForEach(Self.slides) { item in
            Button {
              autoPlay = false
              index = item.id
            } label: {
              Circle()
                .fill(item.id == index ? slide.tint : Color.primary.opacity(0.18))
                .frame(width: item.id == index ? 9 : 7, height: item.id == index ? 9 : 7)
            }
            .buttonStyle(.plain)
            .accessibilityLabel("Go to slide \(item.id + 1)")
          }
        }

        Spacer()

        if let onJumpToPage {
          Button("Open \(slide.targetTitle) →") {
            autoPlay = false
            let dest = slide.targetTab
            dismiss()
            onJumpToPage(dest)
          }
          .font(.caption)
        }

        if index > 0 {
          Button("Back") {
            autoPlay = false
            index -= 1
          }
          .keyboardShortcut(.leftArrow, modifiers: [])
        }

        if index < Self.slides.count - 1 {
          Button("Next") {
            autoPlay = false
            index += 1
          }
          .buttonStyle(BrandButtonStyle())
          .keyboardShortcut(.rightArrow, modifiers: [])
        } else if let onStartStarter {
          Button("Start: Fix and verify") {
            autoPlay = false
            dismiss()
            onStartStarter("fix-and-verify")
          }
          Button("Start: Triage, spec & build") {
            autoPlay = false
            dismiss()
            onStartStarter("triage-spec-build")
          }
          .buttonStyle(BrandButtonStyle())
        } else {
          Button("Done") {
            autoPlay = false
            dismiss()
          }
          .buttonStyle(BrandButtonStyle())
        }
      }
      .padding(.horizontal, 22)
      .padding(.vertical, 12)
    }
    .frame(width: 720, height: 610)
    .background { BrandBackdrop() }
    .task(id: autoPlay) {
      guard autoPlay else { return }
      while autoPlay && !Task.isCancelled {
        try? await Task.sleep(for: .seconds(5))
        guard autoPlay && !Task.isCancelled else { break }
        withAnimation(.easeInOut(duration: 0.2)) {
          if index < Self.slides.count - 1 {
            index += 1
          } else {
            autoPlay = false
          }
        }
      }
    }
  }

  /// Live miniature SwiftUI visual preview tailored to each slide so the Tour doubles
  /// as a crisp, self-contained product demo without needing live model calls.
  @ViewBuilder private var slideVisualPreview: some View {
    switch index {
    case 0:
      HStack(spacing: 8) {
        previewNode("1. Build", "factory.yaml", symbol: "doc.text.fill", color: Brand.purple)
        previewArrow
        previewNode("2. Test", "Isolated worktree", symbol: "arrow.triangle.branch", color: Brand.orange)
        previewArrow
        previewNode("3. Verify", "SuperGauge", symbol: "checkmark.shield.fill", color: Color(red: 0.14, green: 0.64, blue: 0.42))
        previewArrow
        previewNode("4. Improve", "4 Optimizers", symbol: "sparkles", color: Brand.pink)
      }
      .padding(12)
      .frame(maxWidth: .infinity)
      .brandSurface(radius: 12)

    case 1:
      VStack(alignment: .leading, spacing: 10) {
        HStack {
          Text("Interactive routing preview").font(.caption.weight(.semibold))
          Spacer()
          Picker("Request type", selection: $demoNeedsSpec) {
            Text("Ambiguous feature (needs-spec = true)").tag(true)
            Text("Clear bug fix (needs-spec = false)").tag(false)
          }
          .pickerStyle(.segmented)
          .labelsHidden()
          .frame(maxWidth: 380)
        }
        HStack(spacing: 8) {
          previewNode("Triage", "Classifies scope", symbol: "magnifyingglass", color: Brand.purple)
          previewArrow
          previewNode(
            "Spec",
            demoNeedsSpec ? "Human gate · Pauses" : "Skipped automatically",
            symbol: demoNeedsSpec ? "lock.fill" : "forward.fill",
            color: demoNeedsSpec ? Brand.orange : Color.secondary,
            dimmed: !demoNeedsSpec
          )
          previewArrow
          previewNode("Implement", "Code + tests", symbol: "hammer.fill", color: Brand.purple)
          previewArrow
          previewNode("Verify", "Human gate · Ship", symbol: "checkmark.seal.fill", color: Color(red: 0.14, green: 0.64, blue: 0.42))
        }
      }
      .padding(12)
      .frame(maxWidth: .infinity, alignment: .leading)
      .brandSurface(radius: 12)

    case 2:
      HStack(spacing: 10) {
        VStack(alignment: .leading, spacing: 4) {
          Label("skills/merge-risk/SKILL.md", systemImage: "shield.checkered")
            .font(.caption.weight(.semibold)).foregroundStyle(Brand.purple)
          Text("Alignment · Impact · Verification · Rollback · Error detection")
            .font(.caption2).foregroundStyle(.secondary)
        }
        .padding(10).frame(maxWidth: .infinity, alignment: .leading).outlinedSurface(radius: 9)

        VStack(alignment: .leading, spacing: 4) {
          Label("skills/ui-verification/SKILL.md", systemImage: "photo.on.rectangle.angled")
            .font(.caption.weight(.semibold)).foregroundStyle(Color(red: 0.14, green: 0.64, blue: 0.42))
          Text("Walk path · Capture .superqode/factory-proof/ · Record Gotchas")
            .font(.caption2).foregroundStyle(.secondary)
        }
        .padding(10).frame(maxWidth: .infinity, alignment: .leading).outlinedSurface(radius: 9)
      }
      .padding(10)
      .brandSurface(radius: 12)

    case 3:
      HStack(spacing: 12) {
        SuperGaugeMark(verdict: .ship, size: 54, animating: false)
        VStack(alignment: .leading, spacing: 5) {
          HStack(spacing: 6) {
            SuperGaugeBadge(verdict: .ship, showWordmark: true)
            FactoryMergeRiskBadge(level: .low)
            Label("Visual proof attached", systemImage: "photo.fill")
              .font(.system(size: 10, weight: .semibold))
              .foregroundStyle(Brand.purple)
              .padding(.horizontal, 7).padding(.vertical, 3)
              .background(Brand.purple.opacity(0.11), in: Capsule())
          }
          Text("4/4 protected checks passed · OS sandbox isolated · Two-way door rollback · Ready for Touch ID approval.")
            .font(.caption2).foregroundStyle(.secondary)
        }
        Spacer(minLength: 0)
      }
      .padding(12)
      .frame(maxWidth: .infinity, alignment: .leading)
      .brandSurface(radius: 12)

    default:
      HStack(spacing: 10) {
        ForEach([
          ("Native", "Baseline search"),
          ("GEPA", "Prompt evolution"),
          ("MetaHarness", "Harness tuning"),
          ("Omni", "Multi-strategy"),
        ], id: \.0) { name, note in
          VStack(alignment: .leading, spacing: 3) {
            Text(name).font(.caption.weight(.bold)).foregroundStyle(Brand.purple)
            Text(note).font(.caption2).foregroundStyle(.secondary)
          }
          .padding(9).frame(maxWidth: .infinity, alignment: .leading).outlinedSurface(radius: 8)
        }
      }
      .padding(10)
      .brandSurface(radius: 12)
    }
  }

  private var previewArrow: some View {
    Image(systemName: "arrow.right")
      .font(.caption2.weight(.bold))
      .foregroundStyle(.tertiary)
  }

  private func previewNode(_ title: String, _ detail: String, symbol: String, color: Color, dimmed: Bool = false) -> some View {
    VStack(alignment: .leading, spacing: 3) {
      HStack(spacing: 4) {
        Image(systemName: symbol).font(.caption2.weight(.semibold)).foregroundStyle(color)
        Text(title).font(.caption.weight(.semibold))
      }
      Text(detail).font(.caption2).foregroundStyle(.secondary).lineLimit(1)
    }
    .padding(8)
    .frame(maxWidth: .infinity, alignment: .leading)
    .background(color.opacity(dimmed ? 0.04 : 0.10), in: RoundedRectangle(cornerRadius: 8, style: .continuous))
    .overlay(RoundedRectangle(cornerRadius: 8, style: .continuous).strokeBorder(color.opacity(dimmed ? 0.15 : 0.30), lineWidth: 1))
    .opacity(dimmed ? 0.65 : 1)
  }
}
