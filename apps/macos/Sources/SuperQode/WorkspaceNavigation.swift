import SwiftUI

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
    VStack(spacing: 8) {
      Button { app.showWelcome = true } label: { BrandMark().frame(width: 30, height: 30).padding(.vertical, 16) }
        .buttonStyle(.plain).accessibilityLabel("Welcome to SuperQode")
      ForEach(WorkspaceNavigationGroup.all) { group in
        let selected = group.sections.contains(app.section)
        Button {
          app.section = group.sections.first(where: {
            WorkspaceNavigationGroup.available($0, hasProject: !app.projectID.isEmpty)
          }) ?? group.sections[0]
        } label: {
          VStack(spacing: 6) {
            Image(systemName: group.symbol).font(.system(size: 18, weight: .medium))
            Text(group.title).font(.system(size: 9, weight: .medium)).lineLimit(1)
          }.frame(width: 64, height: 54)
            .foregroundStyle(selected ? Color.qAccent : Color.primary.opacity(0.65))
            .background(selected ? Color.qAccent.opacity(0.13) : Color.clear, in: RoundedRectangle(cornerRadius: 10))
        }.buttonStyle(.plain).help(group.sections.map(Sections.title(for:)).joined(separator: " · "))
          .accessibilityLabel(group.title).accessibilityAddTraits(selected ? .isSelected : [])
          .disabled(!group.sections.contains { WorkspaceNavigationGroup.available($0, hasProject: !app.projectID.isEmpty) })
      }
      Spacer(minLength: 12)
      Button { app.showFeatureBrowser.toggle() } label: {
        VStack(spacing: 6) {
          Image(systemName: "square.grid.2x2").font(.system(size: 18))
          Text("Features").font(.system(size: 9, weight: .medium))
        }.frame(width: 64, height: 50)
      }.buttonStyle(.plain).help("Explore all SuperQode features").accessibilityLabel("All features")
        .popover(isPresented: $app.showFeatureBrowser, arrowEdge: .trailing) {
          FeatureBrowserView().environmentObject(app)
        }
      SettingsLink {
        VStack(spacing: 6) {
          Image(systemName: "gearshape").font(.system(size: 18))
          Text("Settings").font(.system(size: 9, weight: .medium))
        }.frame(width: 64, height: 50)
      }.buttonStyle(.plain).help("Settings")
    }.padding(.horizontal, 4).padding(.bottom, 12).frame(width: 72)
      .background(Color.qPanel).disabled(app.openingProject || app.restoringNavigation)
  }
}

struct WorkspaceFeatureBar: View {
  @EnvironmentObject var app: Workspace
  private var group: WorkspaceNavigationGroup { .containing(app.section) }
  var body: some View {
    HStack(spacing: 6) {
      ForEach(group.sections, id: \.self) { section in
        Button { app.section = section } label: {
          Label(Sections.title(for: section), systemImage: WorkspaceNavigationGroup.symbol(for: section))
            .font(.system(size: 11, weight: app.section == section ? .semibold : .regular))
            .padding(.horizontal, 10).padding(.vertical, 8)
            .foregroundStyle(app.section == section ? Color.qAccent : .secondary)
            .background(app.section == section ? Color.qAccent.opacity(0.12) : Color.clear, in: RoundedRectangle(cornerRadius: 7))
        }.buttonStyle(.plain).disabled(!WorkspaceNavigationGroup.available(section, hasProject: !app.projectID.isEmpty))
          .accessibilityAddTraits(app.section == section ? .isSelected : [])
      }
      Spacer(minLength: 0)
      if !app.repositoryPanels.isEmpty {
        Menu {
          ForEach(app.repositoryPanels, id: \.self) { section in
            Button { app.section = section } label: { Label(Sections.title(for: section), systemImage: WorkspaceNavigationGroup.symbol(for: section)) }
          }
        } label: { Label("Pinned", systemImage: "pin") }.menuStyle(.borderlessButton).fixedSize()
      }
      Button { app.showFeatureBrowser = true } label: { Image(systemName: "square.grid.2x2").padding(8) }
        .buttonStyle(.plain).help("All features").accessibilityLabel("Explore all features")
    }.padding(.horizontal, 14).padding(.bottom, 6)
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
                  Image(systemName: WorkspaceNavigationGroup.symbol(for: section)).frame(width: 22).foregroundStyle(Color.qAccent)
                  Text(Sections.title(for: section)).font(.system(size: 12, weight: .medium))
                  if section == "Super Agent" { Text("PREVIEW").font(.system(size: 8, weight: .bold)).foregroundStyle(.secondary) }
                  Spacer()
                  if app.section == section { Image(systemName: "checkmark").font(.caption).foregroundStyle(Color.qAccent) }
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
