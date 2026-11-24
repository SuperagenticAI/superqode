import SwiftUI

struct FactoryNavigationHeader: View {
  let navigation: FactoryNavigation
  var badges: FactorySidebarBadges = FactorySidebarBadges()
  @Environment(\.colorScheme) private var scheme
  @Environment(\.colorSchemeContrast) private var contrast

  @ViewBuilder
  private func trailingBadge(for destination: String) -> some View {
    if destination == "Runs" {
      if badges.pendingGates > 0 {
        Text("\(badges.pendingGates)")
          .font(.system(size: 10, weight: .bold).monospacedDigit())
          .foregroundStyle(.white)
          .padding(.horizontal, 5.5)
          .padding(.vertical, 1.5)
          .background(Brand.orange, in: Capsule())
      } else if badges.isRunning {
        FactoryStatusDot(status: .running, size: 6)
      } else if badges.readyToShip {
        FactoryStatusDot(status: .succeeded, size: 6)
      }
    } else if destination == "Configuration", badges.hasUnappliedControls {
      Circle().fill(Brand.orange).frame(width: 6, height: 6)
    } else if destination == "Definition", badges.hasUnsavedDraft {
      Circle().fill(Brand.purple.opacity(0.75)).frame(width: 6, height: 6)
    }
  }

  var body: some View {
    VStack(alignment: .leading, spacing: 16) {
      HStack(spacing: 8) {
        FactoryStudioEmblem(size: 22)
        Text("Factory Studio")
          .font(.headline.weight(.bold))
          .foregroundStyle(
            contrast == .increased
              ? AnyShapeStyle(Color.primary)
              : AnyShapeStyle(Brand.wordmarkGradient(scheme))
          )
      }
      .padding(.horizontal, 8)
      ScrollView {
      VStack(alignment: .leading, spacing: 14) {
        ForEach(FactoryNavigation.groups) { group in
          let selected = navigation.group.id == group.id
          VStack(alignment: .leading, spacing: 3) {
          nativeButton("factory.group." + group.id, action: { navigation.selectGroup(group.id) }, padded: false,
            title: group.title + (selected ? ", selected" : "")) {
            HStack(spacing: 8) {
              FactoryGroupMark(id: group.id, selected: selected, size: 20)
              Text(group.title).font(.system(size: 13, weight: .semibold))
            }
              .frame(maxWidth: .infinity, alignment: .leading).padding(.horizontal, 8).padding(.vertical, 6)
              .background(selected && group.destinations.count == 1 ? Color.primary.opacity(0.10) : .clear, in: RoundedRectangle(cornerRadius: 6))
          }
          if group.destinations.count > 1 {
          ForEach(group.destinations, id: \.self) { destination in
            let item = FactoryNavigation.tabs.first { $0.id == destination }!
            let selected = navigation.selection == item.id
            nativeButton("factory.tab." + item.id, action: { navigation.select(item.id) }, padded: false,
              title: item.title + (selected ? ", selected" : "")) {
              HStack(spacing: 6) {
                Text(item.title).font(.system(size: 12, weight: selected ? .semibold : .regular))
                Spacer(minLength: 4)
                trailingBadge(for: item.id)
              }
                .frame(maxWidth: .infinity, alignment: .leading).padding(.leading, 14).padding(.trailing, 8).padding(.vertical, 6)
                .background(selected ? Color.primary.opacity(0.10) : Color.clear, in: RoundedRectangle(cornerRadius: 6))
            }.accessibilityAddTraits(selected ? .isSelected : [])
          }
          }
          }
        }
      }.padding(.trailing, 4)
      }
      Text("Build here. Run on your own host.").font(.caption).foregroundStyle(.secondary).padding(.horizontal, 8)
    }.accessibilityLabel("Factory navigation")
  }
}
