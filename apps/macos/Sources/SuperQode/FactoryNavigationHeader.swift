import SwiftUI

struct FactoryNavigationHeader: View {
  let navigation: FactoryNavigation
  var body: some View {
    VStack(alignment: .leading, spacing: 9) {
      HStack(spacing: 6) {
        ForEach(FactoryNavigation.groups) { group in
          let selected = navigation.group.id == group.id
          nativeButton("factory.group." + group.id, action: { navigation.selectGroup(group.id) }, padded: false,
            title: group.title + (selected ? ", selected" : "")) {
            Text(group.title).font(.system(size: 13, weight: selected ? .semibold : .regular))
              .frame(maxWidth: .infinity).padding(.vertical, 9)
              .background(selected ? Color.primary.opacity(0.10) : Color.qPanel, in: RoundedRectangle(cornerRadius: 7))
          }.accessibilityAddTraits(selected ? .isSelected : [])
        }
      }.accessibilityLabel("Factory workflow")
      if navigation.destinations.count > 1 {
        HStack(spacing: 5) {
          ForEach(navigation.destinations, id: \.id) { item in
            let selected = navigation.selection == item.id
            nativeButton("factory.tab." + item.id, action: { navigation.select(item.id) }, padded: false,
              title: item.title + (selected ? ", selected" : "")) {
              Text(item.title).font(.system(size: 12, weight: selected ? .semibold : .regular))
                .padding(.horizontal, 10).padding(.vertical, 6)
                .background(selected ? Color.primary.opacity(0.07) : Color.clear, in: RoundedRectangle(cornerRadius: 6))
            }.accessibilityAddTraits(selected ? .isSelected : [])
          }
          Spacer(minLength: 0)
        }.accessibilityLabel(navigation.group.title + " pages")
      }
      Text(navigation.group.detail).font(.caption).foregroundStyle(.secondary).fixedSize(horizontal: false, vertical: true)
    }
  }
}
