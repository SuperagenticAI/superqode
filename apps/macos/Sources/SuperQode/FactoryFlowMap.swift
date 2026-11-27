import SwiftUI

struct FactoryFlowNode: Identifiable {
  let id: Int
  let title: String
  let symbol: String
  let completed: Bool
}

/// The selected node is a page, not a claim that its work has completed.
struct FactoryFlowMap: View {
  let nodes: [FactoryFlowNode]
  let selection: Int
  var working = false
  var enabled = true
  var onSelect: ((Int) -> Void)?
  @Environment(\.accessibilityReduceMotion) private var reduceMotion

  var body: some View {
    ScrollView(.horizontal, showsIndicators: false) {
      HStack(spacing: 8) {
        ForEach(nodes) { node in
          if node.id != nodes.first?.id {
            Image(systemName: "chevron.right").font(.caption2).foregroundStyle(.tertiary)
          }
          Button { onSelect?(node.id) } label: {
            VStack(spacing: 6) {
              ZStack {
                RoundedRectangle(cornerRadius: 16)
                  .fill(node.id == selection ? Brand.purple.opacity(0.14) : Color.primary.opacity(0.035))
                RoundedRectangle(cornerRadius: 16)
                  .strokeBorder(node.id == selection ? Brand.purple.opacity(0.65) : Color.primary.opacity(0.08), lineWidth: node.id == selection ? 2 : 1)
                Image(systemName: node.completed ? "checkmark" : node.symbol)
                  .font(.system(size: 21, weight: .medium))
                  .foregroundStyle(node.completed ? Color.green : node.id == selection ? Brand.purple : Color.secondary)
                  .symbolEffect(.pulse, options: .repeating, isActive: working && node.id == selection && !reduceMotion)
              }.frame(width: 52, height: 52)
              Text(node.title).font(.caption.weight(node.id == selection ? .semibold : .regular))
                .foregroundStyle(node.id == selection ? Color.primary : Color.secondary)
            }.frame(minWidth: 76).padding(.vertical, 4)
              .contentShape(Rectangle())
          }.buttonStyle(FactoryFlowButtonStyle())
            .disabled(onSelect == nil || !enabled)
            .accessibilityLabel(node.title + (node.completed ? ", completed" : node.id == selection ? ", selected" : ""))
        }
      }.padding(.horizontal, 2)
    }
    .animation(reduceMotion ? nil : .spring(response: 0.35, dampingFraction: 0.8), value: selection)
    .accessibilityIdentifier("factory.flow.map")
  }
}

private struct FactoryFlowButtonStyle: ButtonStyle {
  @Environment(\.accessibilityReduceMotion) private var reduceMotion
  func makeBody(configuration: Configuration) -> some View {
    configuration.label.scaleEffect(configuration.isPressed && !reduceMotion ? 0.96 : 1)
      .animation(reduceMotion ? nil : .spring(response: 0.22, dampingFraction: 0.7), value: configuration.isPressed)
  }
}
