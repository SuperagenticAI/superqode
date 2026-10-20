import AppKit
import SwiftUI

enum BetaRelease {
  static var version: String {
    Bundle.main.object(forInfoDictionaryKey: "CFBundleShortVersionString") as? String
      ?? "Development"
  }
  static let downloads = URL(string: "https://superqode.dev")!
  static let feedback = URL(string: "https://github.com/SuperagenticAI/superqode/issues")!
}

struct BetaGuideView: View {
  @DialogDismiss private var dismiss
  var body: some View {
    VStack(alignment: .leading, spacing: 20) {
      HStack(spacing: 14) {
        BrandMark().frame(width: 44, height: 44)
        VStack(alignment: .leading, spacing: 4) {
          Text("SuperQode Public Beta").font(.title2.bold())
          Text("Version \(BetaRelease.version) · Apple Silicon · macOS 14 or later")
            .font(.caption).foregroundStyle(.secondary)
        }
      }
      ScrollView {
        VStack(alignment: .leading, spacing: 18) {
          guidance(
            "Start with a safe project",
            "Use a Git repository with a backup or committed checkpoint. Open it, connect an agent or model, and describe a small change. Review the diff before keeping the result."
          )
          guidance(
            "Understand execution and costs",
            "Agents and terminal commands run with your Mac user's access. SuperQode is not an operating-system sandbox. Review commands and permissions carefully. Your chosen provider may charge for coding, model tests, evaluation or optimization."
          )
          guidance(
            "Your data and credentials",
            "There is no SuperQode cloud history or account service. Your selected provider or remote agent receives the requests and context sent to it. Optional app-managed keys use macOS Keychain. Local history and evidence exports may contain code or sensitive content; review exports before sharing."
          )
          guidance(
            "Beta limitations",
            "Connection support depends on the installed agent, its advertised capabilities and your account. Experimental routes and advanced workflows may fail. Full terminal feature parity, remote access and Intel Macs are not included. See the download page for the routes tested with real accounts in this release."
          )
          guidance(
            "Updates and feedback",
            "Updates are manual: download a newer signed beta, quit SuperQode, and replace it in Applications. There is no automatic updater. Include the app version, macOS version, agent version and steps to reproduce in a report. Remove credentials and private project content first."
          )
        }.padding(.trailing, 8)
      }.frame(maxHeight: 440)
      HStack {
        Link("Downloads & release notes", destination: BetaRelease.downloads)
        Link("Report an issue", destination: BetaRelease.feedback)
        Spacer()
        Button("Done") { dismiss() }.keyboardShortcut(.defaultAction)
      }
    }.padding(28).frame(width: 640)
  }

  private func guidance(_ title: String, _ text: String) -> some View {
    VStack(alignment: .leading, spacing: 6) {
      Text(title).font(.headline)
      Text(text).font(.body).foregroundStyle(.secondary).textSelection(.enabled)
        .fixedSize(horizontal: false, vertical: true)
    }
  }
}
