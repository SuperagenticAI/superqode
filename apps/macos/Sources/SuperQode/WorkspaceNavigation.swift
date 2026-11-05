import SwiftUI

/// One publication per navigation intent. View callbacks must not publish
/// dependent pane changes while SwiftUI is flushing its current view graph.
struct WorkbenchNavigationState: Equatable {
  var section = "Workspace"
  var drawer = ""
  var expanded = false
  var inspector = false
  var filesMounted = false
  var studioMounted = false

  mutating func select(_ destination: String) {
    section = destination
    switch destination {
    case "Review": inspector = true; drawer = ""; expanded = false
    case "Files", "Terminal", "Checkpoints":
      drawer = destination; expanded = destination == "Files"
      if destination == "Files" { filesMounted = true }
    case "Workspace": closeExpandedDrawer()
    case "Harness Studio": studioMounted = true
    default: break
    }
  }

  mutating func closeExpandedDrawer() {
    if expanded { drawer = ""; expanded = false }
  }
}

struct WorkspaceNavigationGroup: Identifiable {
  let id: String
  let title: String
  let symbol: String
  let sections: [String]

  static let all: [Self] = [
    .init(id: "build", title: "Build", symbol: "chevron.left.forwardslash.chevron.right",
      sections: ["Workspace", "Review", "Files", "Terminal", "Checkpoints"]),
    .init(id: "harness", title: "Harnesses", symbol: "square.stack.3d.up",
      sections: ["Harness Hub", "Harness Studio", "Super Agent"]),
    .init(id: "quality", title: "Quality", symbol: "checkmark.seal",
      sections: ["Evaluations", "Optimization"]),
    .init(id: "local", title: "Local AI", symbol: "cpu", sections: ["Models"]),
    .init(id: "threads", title: "Threads", symbol: "bubble.left.and.bubble.right",
      sections: ["Threads", "Agent activity"]),
    .init(id: "tools", title: "Tools", symbol: "wrench.and.screwdriver", sections: ["Tools"]),
  ]

  static func usesCodingWorkspace(_ section: String) -> Bool {
    isWorkbench(section) || !all.contains { $0.sections.contains(section) }
  }
  static func isWorkbench(_ section: String) -> Bool {
    ["Workspace", "Review", "Files", "Terminal", "Checkpoints"].contains(section)
  }
  static func containing(_ section: String) -> Self { all.first { $0.sections.contains(section) } ?? all[0] }
  static func symbol(for section: String) -> String {
    Sections.icons[Sections.names.firstIndex(of: section) ?? 0]
  }
  static func available(_ section: String, hasProject: Bool) -> Bool {
    hasProject || ["Models", "Agent activity", "Workspace"].contains(section)
  }
}

struct WorkspaceNavigationRail: View {
  @EnvironmentObject var app: Workspace
  var body: some View {
    VStack(spacing: 4) {
      Button { app.showWelcome = true } label: { BrandMark().frame(width: 30, height: 30).padding(.vertical, 10) }
        .buttonStyle(.plain).accessibilityLabel("Welcome to SuperQode")
      ForEach(["Workspace", "Harness Hub", "Harness Studio", "Super Agent", "Evaluations", "Optimization", "Models", "Tools"], id: \.self) { section in
        let selected = section == "Workspace"
          ? WorkspaceNavigationGroup.isWorkbench(app.section) || ["Threads", "Agent activity"].contains(app.section)
          : app.section == section
        Button { app.section = section } label: {
          VStack(spacing: 5) {
            Image(systemName: section == "Workspace" ? "bubble.left.and.bubble.right" : WorkspaceNavigationGroup.symbol(for: section))
              .font(.system(size: 17, weight: .medium))
            Text(section == "Workspace" ? "Threads" : Sections.title(for: section))
              .font(.system(size: 11, weight: .medium)).lineLimit(1).fixedSize(horizontal: true, vertical: false)
          }.frame(width: 104, height: 52)
            .foregroundStyle(selected ? Color.primary : Color.primary.opacity(0.65))
            .background(selected ? Color.primary.opacity(0.07) : Color.clear, in: RoundedRectangle(cornerRadius: 8))
        }.buttonStyle(.plain).help(Sections.title(for: section))
          .accessibilityLabel(section == "Workspace" ? "Threads workspace" : Sections.title(for: section))
          .accessibilityAddTraits(selected ? .isSelected : [])
          .disabled(!WorkspaceNavigationGroup.available(section, hasProject: !app.projectID.isEmpty))
      }
      Spacer(minLength: 12)
      Button { app.showFeatureBrowser.toggle() } label: {
        VStack(spacing: 6) {
          Image(systemName: "square.grid.2x2").font(.system(size: 18))
          Text("Features").font(.system(size: 9, weight: .medium))
        }.frame(width: 104, height: 50)
      }.buttonStyle(.plain).help("Explore all SuperQode features").accessibilityLabel("All features")
        .popover(isPresented: $app.showFeatureBrowser, arrowEdge: .trailing) {
          FeatureBrowserView().environmentObject(app)
        }
      SettingsLink {
        VStack(spacing: 6) {
          Image(systemName: "gearshape").font(.system(size: 18))
          Text("Settings").font(.system(size: 9, weight: .medium))
        }.frame(width: 104, height: 50)
      }.buttonStyle(.plain).help("Settings")
    }.padding(.horizontal, 4).padding(.bottom, 12).frame(width: 112)
      .background(Color.qPanel).disabled(app.openingProject || app.restoringNavigation)
  }
}

struct FeatureBrowserView: View {
  @EnvironmentObject var app: Workspace
  var body: some View {
    VStack(alignment: .leading, spacing: 18) {
      HStack {
        VStack(alignment: .leading, spacing: 5) {
          Text("Explore SuperQode").font(.title2.weight(.semibold))
          Text("Build, verify and improve your coding agents.").font(.caption).foregroundStyle(.secondary)
        }
        Spacer()
        Button { app.showFeatureBrowser = false } label: { Image(systemName: "xmark").padding(6) }
          .buttonStyle(.plain).accessibilityLabel("Close all features")
      }
      LazyVGrid(columns: [GridItem(.flexible()), GridItem(.flexible())], alignment: .leading, spacing: 18) {
        ForEach(WorkspaceNavigationGroup.all) { group in
          VStack(alignment: .leading, spacing: 6) {
            Text(group.title.uppercased()).font(.system(size: 10, weight: .bold)).tracking(1.2).foregroundStyle(.secondary)
            ForEach(group.sections, id: \.self) { section in
              Button {
                app.section = section; app.showFeatureBrowser = false
              } label: {
                HStack(spacing: 9) {
                  Image(systemName: WorkspaceNavigationGroup.symbol(for: section)).frame(width: 22).foregroundStyle(.secondary)
                  Text(Sections.title(for: section)).font(.system(size: 12, weight: .medium))
                  if section == "Super Agent" { Text("PREVIEW").font(.system(size: 8, weight: .bold)).foregroundStyle(.secondary) }
                  Spacer()
                  if app.section == section { Image(systemName: "checkmark").font(.caption).foregroundStyle(.primary) }
                }.padding(9).foregroundStyle(.primary)
                  .background(Color.qPanel, in: RoundedRectangle(cornerRadius: 7))
                  .overlay(RoundedRectangle(cornerRadius: 7).stroke(Color.primary.opacity(0.12)))
              }.buttonStyle(.plain).disabled(!WorkspaceNavigationGroup.available(section, hasProject: !app.projectID.isEmpty))
            }
          }.frame(maxHeight: .infinity, alignment: .top)
        }
      }
      Divider()
      Button { app.showFeatureBrowser = false; app.presentCommandPalette() } label: {
        HStack { Label("Search actions", systemImage: "command"); Spacer(); Text("⌘K").foregroundStyle(.secondary) }.font(.caption)
      }.buttonStyle(.plain)
    }.padding(22).frame(width: 550).background(Color.qPanel)
  }
}
