import SwiftUI

struct ConnectionSearchField: View {
  let title: String
  @Binding var text: String

  var body: some View {
    HStack(spacing: 8) {
      Image(systemName: "magnifyingglass").font(.body).foregroundStyle(.secondary).accessibilityHidden(true)
      TextField(title, text: $text).font(.body).textFieldStyle(.plain).accessibilityLabel(title)
      if !text.isEmpty {
        Button { text = "" } label: { Image(systemName: "xmark.circle.fill") }
          .buttonStyle(.plain).foregroundStyle(.secondary).accessibilityLabel("Clear " + title.lowercased())
      }
    }
    .padding(10)
    .background(.primary.opacity(0.055), in: RoundedRectangle(cornerRadius: 7))
  }
}

struct ConnectionCardLabel<Icon: View>: View {
  let title: String
  var subtitle = ""
  var status = ""
  var featured = false
  @ViewBuilder var icon: () -> Icon

  var body: some View {
    HStack(spacing: featured ? 16 : 12) {
      icon().accessibilityHidden(true)
      VStack(alignment: .leading, spacing: 3) {
        Text(title).font(featured ? .title3.weight(.semibold) : .system(size: 15, weight: .semibold)).lineLimit(2)
        if !subtitle.isEmpty {
          Text(subtitle).font(.callout).foregroundStyle(.secondary).lineLimit(2)
        }
        if !status.isEmpty {
          Text(status).font(.caption).foregroundStyle(.secondary)
        }
      }
      Spacer(minLength: 0)
      Image(systemName: "chevron.right").font(.callout).foregroundStyle(.tertiary)
        .accessibilityHidden(true)
    }
    .padding(.horizontal, featured ? 16 : 12)
    .padding(.vertical, 8)
    .frame(minHeight: featured ? 76 : (!subtitle.isEmpty ? 72 : 52))
    .contentShape(Rectangle())
  }
}

struct ConnectionChoiceStyle: ButtonStyle {
  @Environment(\.isEnabled) private var enabled
  var selected = false

  func makeBody(configuration: Configuration) -> some View {
    configuration.label
      .opacity(enabled ? 1 : 0.55)
      .modifier(ConnectionCardSurface(selected: selected, pressed: configuration.isPressed))
  }
}

struct ConnectionCardSurface: ViewModifier {
  var selected = false
  var pressed = false

  func body(content: Content) -> some View {
    let shape = RoundedRectangle(cornerRadius: 7)
    content
      .foregroundStyle(.primary)
      .background(selected ? Color.qAccent.opacity(0.13) : .primary.opacity(pressed ? 0.11 : 0.045), in: shape)
      .overlay(shape.strokeBorder(selected ? Color.qAccent : .primary.opacity(0.10)).allowsHitTesting(false))
  }
}
