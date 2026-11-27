import SwiftUI

/// A presenter-controlled story. It never submits work or creates quality records.
struct FactoryPresentationView: View {
  @Environment(\.dismiss) private var dismiss
  @Environment(\.scenePhase) private var scenePhase
  @Environment(\.accessibilityReduceMotion) private var reduceMotion
  @State private var playback = FactoryPresentationState()

  var body: some View {
    VStack(alignment: .leading, spacing: 20) {
      HStack(spacing: 12) {
        FactoryStudioEmblem(size: 36)
        VStack(alignment: .leading, spacing: 3) {
          Text("Watch a Factory work").font(.title2.bold())
          Text("Fix and verify · Checkout totals").font(.subheadline).foregroundStyle(.secondary)
        }
        Spacer()
        Label("Scripted demo", systemImage: "play.rectangle")
          .font(.caption.bold()).padding(.horizontal, 10).padding(.vertical, 6)
          .background(Brand.purple.opacity(0.12), in: Capsule())
        Button("Close") { dismiss() }.keyboardShortcut(.cancelAction)
      }
      FactoryFlowMap(nodes: FactoryPresentationState.Stage.allCases.map {
        FactoryFlowNode(id: $0.rawValue, title: $0.title, symbol: $0.symbol,
                        completed: $0.rawValue < playback.stage.rawValue)
      }, selection: playback.stage.rawValue, working: playback.playing)
      ScrollView {
        VStack(alignment: .leading, spacing: 14) {
          FactoryPresentationScene(state: playback)
            .id(playback.stage)
            .transition(reduceMotion ? .identity : .opacity.combined(with: .move(edge: .trailing)))
          if playback.stage == .complete {
            FactoryDemoStartView(onCreated: { dismiss() })
              .padding(14).brandSurface()
          }
        }
      }.frame(maxHeight: .infinity)
      Divider()
      HStack(spacing: 12) {
        Button { playback.back() } label: { Label("Back", systemImage: "chevron.left") }
          .disabled(playback.stage == .request)
          .keyboardShortcut(.leftArrow, modifiers: [])
        Button { playback.reset() } label: { Label("Restart", systemImage: "arrow.counterclockwise") }
          .accessibilityIdentifier("factory.presentation.restart")
        Spacer()
        Text("\(playback.stage.rawValue + 1) of \(FactoryPresentationState.Stage.allCases.count)")
          .font(.caption.monospacedDigit()).foregroundStyle(.secondary)
        if playback.waitingForReview {
          Button("Approve demo repair") { playback.approveReview() }
            .buttonStyle(BrandButtonStyle())
            .accessibilityIdentifier("factory.presentation.approve")
        } else {
          Button {
            if playback.playing { playback.pause() } else { playback.play() }
          } label: {
            Label(playback.playing ? "Pause" : "Play demo", systemImage: playback.playing ? "pause.fill" : "play.fill")
          }.disabled(playback.stage == .complete)
            .accessibilityIdentifier("factory.presentation.play")
          Button("Next") { playback.pause(); playback.advance() }
            .buttonStyle(BrandButtonStyle()).disabled(!playback.canAdvance)
            .keyboardShortcut(.rightArrow, modifiers: [])
            .accessibilityIdentifier("factory.presentation.next")
        }
      }
      Text("Illustration only · 0 model calls · 0 files changed · No SuperGauge record or release approval is created.")
        .font(.caption).foregroundStyle(.secondary)
    }.padding(28)
      .frame(minWidth: 880, idealWidth: 1020, maxWidth: 1100, minHeight: 620, idealHeight: 730, maxHeight: 800)
      .background { BrandBackdrop() }
      .animation(reduceMotion ? nil : .spring(response: 0.4, dampingFraction: 0.88), value: playback.stage)
      .task(id: playback.playbackID) {
        while playback.playing && !Task.isCancelled {
          do { try await Task.sleep(for: .seconds(2.8)) } catch { return }
          guard !Task.isCancelled, playback.playing else { return }
          playback.advance()
        }
      }
      .onDisappear { playback.pause() }
      .onChange(of: scenePhase) { _, phase in if phase != .active { playback.pause() } }
      .accessibilityIdentifier("factory.presentation")
  }
}

/// Renderable independently of Workspace, credentials and the desktop engine.
struct FactoryPresentationScene: View {
  let state: FactoryPresentationState
  private var repaired: Bool { state.stage.rawValue >= FactoryPresentationState.Stage.repair.rawValue }
  private var verified: Bool { state.stage.rawValue >= FactoryPresentationState.Stage.verify.rawValue }

  var body: some View {
    VStack(alignment: .leading, spacing: 20) {
      HStack(alignment: .top, spacing: 14) {
        Image(systemName: state.stage.symbol).font(.system(size: 28, weight: .medium))
          .foregroundStyle(state.waitingForReview ? Brand.orange : Brand.purple)
          .frame(width: 58, height: 58)
          .background((state.waitingForReview ? Brand.orange : Brand.purple).opacity(0.1), in: RoundedRectangle(cornerRadius: 17))
        VStack(alignment: .leading, spacing: 7) {
          Text(state.stage.headline).font(.title2.bold())
          Text(state.stage.detail).font(.callout).foregroundStyle(.secondary)
            .fixedSize(horizontal: false, vertical: true)
        }
      }
      HStack(alignment: .top, spacing: 18) {
        VStack(alignment: .leading, spacing: 12) {
          Label(repaired ? "Proposed change" : "The starting code", systemImage: "chevron.left.forwardslash.chevron.right")
            .font(.subheadline.bold())
          Text("def total(values):\n    result = 0\n    for value in values:")
            .font(.system(.callout, design: .monospaced))
          Text(repaired ? "−       result = value\n+       result += value" : "        result = value")
            .font(.system(.callout, design: .monospaced)).foregroundStyle(repaired ? Color.green : Brand.orange)
          Text("    return result").font(.system(.callout, design: .monospaced))
          Text(repaired ? "One changed line. The protected expectations stay the same." : "The running total is replaced on every iteration.")
            .font(.caption).foregroundStyle(.secondary)
        }.frame(maxWidth: .infinity, alignment: .leading).padding(20).brandSurface()
        VStack(alignment: .leading, spacing: 12) {
          Label(verified ? "Illustrated check results" : "Protected expectations", systemImage: "lock.shield")
            .font(.subheadline.bold())
          example("Multiple items", input: "[2, 3]", expected: "5", passes: verified)
          example("Discounts", input: "[8, −3, 1]", expected: "6", passes: verified)
          example("Empty basket", input: "[]", expected: "0", passes: verified)
          Text(verified ? "3 / 3 passing in this scripted example" : "Coding agents do not get to edit these expectations.")
            .font(.caption).foregroundStyle(.secondary)
        }.frame(maxWidth: .infinity, alignment: .leading).padding(20).brandSurface()
      }
      if state.waitingForReview {
        Label("Autoplay is paused. You decide whether this illustrated repair continues.", systemImage: "hand.raised.fill")
          .font(.callout.weight(.medium)).foregroundStyle(Brand.orange)
      } else if state.stage == .complete {
        HStack(spacing: 18) {
          metric("Changed lines", "1")
          metric("Illustrated checks", "3 / 3")
          metric("Model calls", "0")
          metric("Real release", "Not authorized")
        }
      }
    }.padding(24).background(Color.primary.opacity(0.025), in: RoundedRectangle(cornerRadius: 22))
      .accessibilityIdentifier("factory.presentation.scene")
  }
  private func example(_ title: String, input: String, expected: String, passes: Bool) -> some View {
    HStack(spacing: 8) {
      Image(systemName: passes ? "checkmark.circle.fill" : "circle.dashed")
        .foregroundStyle(passes ? Color.green : Color.secondary)
      VStack(alignment: .leading, spacing: 2) {
        Text(title).font(.caption.bold())
        Text(input + " → " + expected).font(.system(.caption, design: .monospaced)).foregroundStyle(.secondary)
      }
      Spacer(minLength: 0)
    }
  }
  private func metric(_ title: String, _ value: String) -> some View {
    VStack(alignment: .leading, spacing: 4) {
      Text(title).font(.caption).foregroundStyle(.secondary)
      Text(value).font(.subheadline.bold())
    }.frame(maxWidth: .infinity, alignment: .leading)
  }
}
