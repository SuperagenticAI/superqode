import SwiftUI

struct FactoryPresentationLaunchCard: View {
  @Environment(\.accessibilityReduceMotion) private var reduceMotion
  @State private var showing = false
  @State private var hovering = false
  var body: some View {
    HStack(spacing: 18) {
      FactoryStudioEmblem(size: 48)
        .rotationEffect(.degrees(hovering && !reduceMotion ? 6 : 0))
      VStack(alignment: .leading, spacing: 5) {
        Text("See a Factory in action").font(.headline)
        Text("Follow a repair from request to human review and verification.")
          .font(.callout).foregroundStyle(.secondary)
        Text("Interactive, scripted demo · No project or API key needed")
          .font(.caption).foregroundStyle(.secondary)
      }
      Spacer(minLength: 8)
      Button { showing = true } label: { Label("Play demo", systemImage: "play.fill") }
        .buttonStyle(BrandButtonStyle())
        .accessibilityIdentifier("welcome.factoryPresentation")
    }.padding(22).brandSurface()
      .onHover { hovering = $0 }
      .animation(reduceMotion ? nil : .spring(response: 0.4, dampingFraction: 0.7), value: hovering)
      .sheet(isPresented: $showing) { FactoryPresentationView() }
  }
}
