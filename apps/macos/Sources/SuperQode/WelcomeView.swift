import SwiftUI

/// A real launch destination, independent of whether a previous project exists.
/// Opening a project is explicit; returning home never discards its drafts.
struct WelcomeView: View {
  @EnvironmentObject var app: Workspace
  @State private var showBetaGuide = false
  var body: some View {
    GeometryReader { geometry in
      ScrollView {
        VStack(spacing: 32) {
          VStack(spacing: 14) {
            BrandMark().frame(width: 82, height: 82).padding(20)
              .background(.primary.opacity(0.035), in: RoundedRectangle(cornerRadius: 28))
              .overlay(RoundedRectangle(cornerRadius: 28).strokeBorder(.primary.opacity(0.06)))
            Text("Welcome to SuperQode").font(.system(size: 36, weight: .semibold))
              .multilineTextAlignment(.center).accessibilityAddTraits(.isHeader)
            Text("Your code. Your agents. Your Mac.")
              .font(.system(size: 16)).foregroundStyle(.secondary)
            Button("Public Beta · \(BetaRelease.version) · Read the beta guide") {
              showBetaGuide = true
            }.buttonStyle(.link).font(.callout)
          }
          Group {
            if geometry.size.width >= 980 {
              HStack(alignment: .top, spacing: 24) {
                startCard.frame(maxWidth: .infinity)
                recentCard.frame(maxWidth: .infinity)
              }
            } else {
              VStack(spacing: 20) {
                startCard
                recentCard
              }
            }
          }.frame(maxWidth: 860)
          HStack(spacing: 24) {
            Button {
              app.showLearningGuide = true
            } label: {
              Label("Getting started", systemImage: "book.closed")
            }
            if !app.project.isEmpty {
              Button("Return to " + string(app.project, "name", "workspace")) {
                app.showWelcome = false
              }
            }
          }.font(.callout)
          HStack(spacing: 7) {
            Circle().fill(app.connected ? Color.green : Color.orange).frame(width: 6, height: 6)
            Text(app.connected ? "Local engine ready" : "Starting local engine…")
            Text("·")
            Text("No SuperQode account needed")
          }.font(.caption).foregroundStyle(.secondary)
        }.padding(.horizontal, 56).padding(.vertical, 48)
          .frame(maxWidth: .infinity)
          .frame(minHeight: geometry.size.height, alignment: .center)
      }.defaultScrollAnchor(.top)
    }.background { BrandBackdrop() }
      .centeredDialog(isPresented: $showBetaGuide, title: "Public Beta") {
        BetaGuideView()
      }
  }
  private var startCard: some View {
    VStack(alignment: .leading, spacing: 20) {
      Label("Start building", systemImage: "chevron.left.forwardslash.chevron.right")
        .font(.headline)
      Text(
        "Open a project, connect the agent or model you already use, then describe your first change."
      )
      .font(.callout).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
      Button(action: app.chooseProject) {
        HStack {
          Label(
            app.openingProject ? "Opening project…" : "Open project…",
            systemImage: "folder.badge.plus")
          Spacer()
          Text("⌘O").opacity(0.65)
        }
      }.buttonStyle(BrandButtonStyle()).disabled(!app.connected || app.openingProject)
      Text("Your project stays on your Mac. Your chosen agent or provider handles model requests.")
        .font(.caption).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
    }.padding(28).frame(maxWidth: .infinity, minHeight: 280, alignment: .topLeading)
      .background(
        Color(nsColor: .controlBackgroundColor).opacity(0.55),
        in: RoundedRectangle(cornerRadius: 20)
      )
      .overlay(RoundedRectangle(cornerRadius: 20).strokeBorder(.primary.opacity(0.08)))
  }
  private var recentCard: some View {
    VStack(alignment: .leading, spacing: 16) {
      Label("Recent projects", systemImage: "clock").font(.headline)
      if app.projects.isEmpty {
        Text("Your projects will appear here.").font(.callout).foregroundStyle(.secondary)
        Text("Already set up an agent in Terminal? You can connect it after opening your project.")
          .font(.caption).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
      } else {
        ForEach(Array(app.projects.prefix(3)), id: \.projectRowID) { project in
          Button {
            app.perform { try await app.open(string(project, "path")) }
          } label: {
            HStack(spacing: 12) {
              Image(systemName: "folder").foregroundStyle(Brand.gradient)
              VStack(alignment: .leading, spacing: 4) {
                Text(string(project, "name", "Project")).font(.system(size: 13, weight: .medium))
                Text((string(project, "path") as NSString).abbreviatingWithTildeInPath)
                  .font(.caption).foregroundStyle(.secondary).lineLimit(1).truncationMode(.middle)
              }
              Spacer(minLength: 0)
              Image(systemName: "chevron.right").font(.caption).foregroundStyle(.tertiary)
            }.padding(10).contentShape(Rectangle())
          }.buttonStyle(.plain).disabled(!app.connected || app.openingProject)
        }
        if app.projects.count > 3 {
          Menu("All recent projects") {
            ForEach(app.projects, id: \.projectRowID) { project in
              Button(string(project, "name", "Project")) {
                app.perform { try await app.open(string(project, "path")) }
              }
            }
          }.font(.caption).disabled(!app.connected || app.openingProject)
        }
      }
    }.padding(28).frame(maxWidth: .infinity, minHeight: 280, alignment: .topLeading)
      .background(.primary.opacity(0.025), in: RoundedRectangle(cornerRadius: 20))
      .overlay(RoundedRectangle(cornerRadius: 20).strokeBorder(.primary.opacity(0.06)))
  }
}
