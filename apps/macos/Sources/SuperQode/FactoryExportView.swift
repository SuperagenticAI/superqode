import AppKit
import CryptoKit
import SwiftUI
import UniformTypeIdentifiers

@MainActor final class FactoryExportLibrary: ObservableObject {
  @Published private(set) var preview: [String: Any] = [:]
  @Published private(set) var package: [String: Any] = [:]
  @Published private(set) var busy = false
  @Published var failure = ""
  private(set) var project = ""
  private var generation = 0
  func enter(_ identity: String) {
    guard project != identity else { return }
    project = identity; generation += 1; preview = [:]; package = [:]; busy = false; failure = ""
  }
  func refresh(_ engine: Engine) async {
    guard !project.isEmpty, !busy else { return }
    generation += 1; let token = generation; let identity = project
    do {
      let result = try await engine.call("factory.export.preview", ["project": identity]) as? [String: Any] ?? [:]
      guard project == identity, generation == token, !Task.isCancelled else { return }
      if string(preview, "snapshot_digest") != string(result, "snapshot_digest") { package = [:] }
      preview = result; failure = ""
    } catch { if project == identity, generation == token, !Task.isCancelled { preview = [:]; package = [:]; failure = error.localizedDescription } }
  }
  func create(_ engine: Engine) async {
    guard !busy, !project.isEmpty, !preview.isEmpty else { return }
    generation += 1; let token = generation; let identity = project; let digest = string(preview, "snapshot_digest")
    busy = true
    defer { if project == identity, generation == token { busy = false } }
    do {
      let result = try await engine.call("factory.export.create", ["project": identity, "digest": digest, "confirmed": true]) as? [String: Any] ?? [:]
      guard project == identity, generation == token else { return }
      guard string(result["manifest"] as? [String: Any] ?? [:], "snapshot_digest") == digest else { throw EngineError(message: "Export differs from the reviewed Factory.") }
      package = result; failure = ""
    } catch { if project == identity, generation == token { package = [:]; failure = error.localizedDescription } }
  }
  func copy(to destination: URL) throws {
    guard !package.isEmpty else { throw EngineError(message: "Create a reviewed source package first.") }
    let source = URL(fileURLWithPath: string(package, "path"))
    let metadata = try source.resourceValues(forKeys: [.fileSizeKey, .isRegularFileKey, .isSymbolicLinkKey])
    guard metadata.isRegularFile == true, metadata.isSymbolicLink != true, (metadata.fileSize ?? Int.max) <= 16_000_000 else {
      throw EngineError(message: "Export archive changed or exceeds its size limit.")
    }
    let data = try Data(contentsOf: source)
    let checksum = "sha256:" + SHA256.hash(data: data).map { String(format: "%02x", $0) }.joined()
    guard checksum == string(package, "sha256") else { throw EngineError(message: "Export archive changed. Create a fresh package.") }
    try data.write(to: destination, options: .withoutOverwriting)
  }
}

struct FactoryExportView: View {
  @EnvironmentObject var app: Workspace
  @ObservedObject var studio: FactoryStudioLibrary
  @ObservedObject var library: FactoryExportLibrary
  var active: Bool
  @State private var confirmation = false
  @State private var reviewedDigest = ""
  @State private var savedPath = ""
  private var idle: Bool { !library.busy && !studio.busy && !studio.acceptance.busy && !app.anyActive }
  private var current: Bool { !studio.expectedFileDigest.isEmpty && string(studio.review, "digest") == studio.expectedFileDigest && string(studio.review, "yaml") == studio.text && string(studio.review, "snapshot_digest") == string(library.preview, "snapshot_digest") }
  var body: some View {
    ScrollView {
      VStack(alignment: .leading, spacing: 20) {
        Text("Take your Factory with you").font(.headline)
        Text("Export editable definitions, components and a pinned snapshot. This app does not need to stay open.").foregroundStyle(.secondary)
        VStack(alignment: .leading, spacing: 8) {
          Label("Run without the desktop app", systemImage: "terminal").font(.subheadline.bold())
          Text("Use the SuperQode CLI or a customer-managed worker on a supported host. Bring your application repository, model access and reviewed runtime build.").font(.caption).foregroundStyle(.secondary)
        }.padding(16).brandSurface()
        VStack(alignment: .leading, spacing: 8) {
          Label("Adapt for another platform", systemImage: "arrow.up.forward.square").font(.subheadline.bold())
          Text("The exported files are yours to edit. Other platforms need an adapter for their workflow and runtime contracts; their execution has not been verified.").font(.caption).foregroundStyle(.secondary)
        }.padding(16).brandSurface()
        if !library.preview.isEmpty {
          Text("\(library.preview["files"] as? [String] == nil ? 0 : (library.preview["files"] as? [String] ?? []).count) declared source files · instructions and checksums included")
            .font(.caption).foregroundStyle(.secondary)
          DisclosureGroup("Files included") {
            ForEach(library.preview["files"] as? [String] ?? [], id: \.self) { Text($0).font(.caption.monospaced()).textSelection(.enabled) }
          }
          Text("Declared context and protected evaluator code can be private. Review the package before sharing. Credential stores, run history, runtime binaries and the application checkout are separate.").font(.caption).foregroundStyle(.secondary)
        }
        if !current { HStack { Text("Check and save the Factory before exporting it.").font(.caption).foregroundStyle(.orange); Button("Review definition") { studio.navigation.select("Definition") } } }
        FactoryActionRow {
          nativeButton("factory.export.create", action: { reviewedDigest = string(library.preview, "snapshot_digest"); confirmation = true }, title: "Create portable package…") { Text("Create portable package…") }
            .disabled(!idle || !current || library.preview.isEmpty)
          Button("Refresh") { Task { await library.refresh(app.engine) } }.disabled(!idle)
        }
        if library.busy { ProgressView().controlSize(.small) }
        if !library.package.isEmpty {
          Label("Package ready", systemImage: "checkmark.circle").font(.subheadline.bold())
          Button("Save a copy…") { saveCopy() }.buttonStyle(BrandButtonStyle())
          DisclosureGroup("Runtime requirements & package details") { CodeBlock(text: pretty(library.package["manifest"])) }
        }
        if !savedPath.isEmpty { Text("Saved to " + savedPath).font(.caption).textSelection(.enabled) }
        if !library.failure.isEmpty { Text(library.failure).font(.caption).foregroundStyle(.orange).textSelection(.enabled) }
      }.frame(maxWidth: 720, alignment: .leading).frame(maxWidth: .infinity, alignment: .leading)
    }
    .task(id: app.projectID + "\n" + String(active)) { guard active else { return }; library.enter(app.projectID); await library.refresh(app.engine) }
    .onChange(of: active) { _, value in if !value { confirmation = false } }
    .onChange(of: app.projectID) { _, _ in confirmation = false; savedPath = "" }
    .factoryConfirmation(
      isPresented: $confirmation,
      title: "Export the reviewed Factory sources?",
      message: "Create a ZIP containing the saved definitions, referenced components and pinned snapshot. Review private context and evaluators before sharing it. Exporting starts no agents or services.",
      kind: .export,
      badges: [
        FactoryConfirmBadge(label: "Portable ZIP", symbol: "shippingbox", color: Color(red: 0.18, green: 0.48, blue: 0.84)),
        FactoryConfirmBadge(label: "No agents started", symbol: "bolt.slash", color: Color(red: 0.14, green: 0.62, blue: 0.42))
      ],
      confirmTitle: "Create package",
      onConfirm: { guard reviewedDigest == string(library.preview, "snapshot_digest"), current else { return }; Task { await library.create(app.engine) } }
    )
  }
  private func saveCopy() {
    let panel = NSSavePanel(); panel.allowedContentTypes = [.zip]
    panel.nameFieldStringValue = "factory-" + string(library.preview, "name", "sources") + ".zip"
    panel.canCreateDirectories = true
    let identity = app.projectID; let digest = string(library.package, "sha256")
    panel.begin { result in
      guard result == .OK, let url = panel.url else { return }
      Task { @MainActor in
        guard app.projectID == identity, string(library.package, "sha256") == digest else { return }
        do { try library.copy(to: url); savedPath = url.path; library.failure = "" }
        catch { library.failure = error.localizedDescription }
      }
    }
  }
}
