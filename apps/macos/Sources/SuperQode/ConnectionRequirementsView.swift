import SwiftUI

struct ConnectionRequirementsView: View {
  let requirements: [[String: Any]]
  var body: some View {
    VStack(alignment: .leading, spacing: 12) {
      Text("Required local components").font(.headline)
      ForEach(requirements, id: \.projectRowID) { row in
        let installed = row["installed"] as? Bool == true
        VStack(alignment: .leading, spacing: 6) {
          Label(string(row, "name") + (installed ? " · Installed" : " · Missing"),
            systemImage: installed ? "checkmark.circle" : "arrow.down.circle")
          if row["required_for_connection"] as? Bool == false {
            Text("Needed for sign-in from this screen. An installed SDK can connect using an existing vendor login without this CLI.")
              .font(.caption).foregroundStyle(.secondary)
          }
          if !installed { Text(string(row, "instruction")).font(.callout).textSelection(.enabled) }
          if let url = URL(string: string(row, "docs_url")), url.scheme == "https",
            url.user == nil, url.password == nil {
            Link("Setup documentation", destination: url).font(.caption)
          }
        }
      }
      if requirements.contains(where: { $0["installed"] as? Bool != true }) {
        Text("Complete setup, then choose Check installation again. Each action stays disabled until its required components are detected. Installation does not verify your account or subscription.")
          .font(.caption).foregroundStyle(.secondary)
      }
    }.padding(14).brandSurface()
  }
}
