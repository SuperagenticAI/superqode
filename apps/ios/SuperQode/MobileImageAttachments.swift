import SwiftUI
import PhotosUI
import ImageIO
import UniformTypeIdentifiers

struct MobileImageAttachments: View {
  @Binding var draft: LocalDraft
  let frozen: Bool
  @EnvironmentObject private var store: CompanionStore
  @State private var picked: [PhotosPickerItem] = []
  @State private var importing = false
  @State private var loading = false
  @State private var issue = ""
  var body: some View {
    CompanionCard {
      Label("Images and screenshots", systemImage: "photo.on.rectangle").font(.headline)
      Text("Up to four images, 4 MB each. Draft images stay protected on this iPhone until you send them to your Mac. Model and agent image support still applies.").font(.caption).foregroundStyle(.secondary)
      ForEach(draft.images ?? []) { image in
        HStack {
          Label(image.name, systemImage: "photo").lineLimit(1)
          Text(ByteCountFormatter.string(fromByteCount: Int64(image.bytes), countStyle: .file)).font(.caption).foregroundStyle(.secondary)
          Spacer()
          Button("Remove", role: .destructive) { Task { await remove(image) } }.font(.caption)
        }
      }
      HStack {
        PhotosPicker(selection: $picked, maxSelectionCount: max(1, 4 - (draft.images ?? []).count), matching: .images) { Label("Add photos", systemImage: "photo.badge.plus") }
        Button("Choose files") { importing = true }
      }.disabled((draft.images ?? []).count >= 4 || !store.features.flag("image_upload"))
      if store.isPreview { Text("Pair your Mac to attach your own images.").font(.caption).foregroundStyle(.secondary) }
      if loading { ProgressView("Protecting image draft…") }
      if !issue.isEmpty { Text(issue).font(.caption).foregroundStyle(CompanionTheme.warning) }
      if !store.features.flag("image_upload") { Text("Update the Mac build to enable image uploads.").font(.caption).foregroundStyle(.secondary) }
    }.disabled(frozen || loading || store.isPreview)
      .onChange(of: picked) { _, values in Task {
        loading = true; issue = ""
        defer { loading = false; picked = [] }
        do {
          for item in values {
            guard let bytes = try await item.loadTransferable(type: Data.self) else { continue }
            try await attach(bytes)
          }
        } catch { issue = error.localizedDescription }
      } }
      .fileImporter(isPresented: $importing, allowedContentTypes: [.image], allowsMultipleSelection: true) { result in Task {
        loading = true; issue = ""
        defer { loading = false }
        do {
          for url in try result.get() {
            let access = url.startAccessingSecurityScopedResource()
            defer { if access { url.stopAccessingSecurityScopedResource() } }
            let bytes = try Data(contentsOf: url, options: .mappedIfSafe)
            try await attach(bytes)
          }
        } catch { issue = error.localizedDescription }
      } }
  }
  private func attach(_ bytes: Data) async throws {
    guard (draft.images ?? []).count < 4 else { throw CompanionError("Attach up to four images.") }
    let prepared = try await Task.detached(priority: .userInitiated) { () -> (Data, String) in
      guard bytes.count <= 20 * 1024 * 1024, let source = CGImageSourceCreateWithData(bytes as CFData, nil), let type = CGImageSourceGetType(source) as String? else { throw CompanionError("Choose a supported image smaller than 20 MB before conversion.") }
      let kind = UTType(type)
      if let suffix = kind?.preferredFilenameExtension, ["png", "jpg", "jpeg", "gif", "webp"].contains(suffix) { return (bytes, "image." + suffix) }
      guard let thumb = CGImageSourceCreateThumbnailAtIndex(source, 0, [kCGImageSourceCreateThumbnailFromImageAlways: true, kCGImageSourceThumbnailMaxPixelSize: 2048, kCGImageSourceCreateThumbnailWithTransform: true] as CFDictionary) else { throw CompanionError("This image could not be converted. Choose PNG or JPEG.") }
      let data = NSMutableData()
      guard let output = CGImageDestinationCreateWithData(data, UTType.jpeg.identifier as CFString, 1, nil) else { throw CompanionError("Image conversion is unavailable.") }
      CGImageDestinationAddImage(output, thumb, [kCGImageDestinationLossyCompressionQuality: 0.9] as CFDictionary)
      guard CGImageDestinationFinalize(output) else { throw CompanionError("Image conversion failed.") }
      return (data as Data, "image.jpg")
    }.value
    let image = try await store.drafts.stageImage(draft: draft.id, name: prepared.1, data: prepared.0)
    draft.images = (draft.images ?? []) + [image]
    if !store.isPreview { try await store.drafts.save(draft) }
  }
  private func remove(_ image: DraftImage) async {
    draft.images?.removeAll { $0.id == image.id }
    if !store.isPreview {
      do { try await store.drafts.save(draft); try await store.drafts.removeImage(draft: draft.id, image: image) }
      catch { issue = error.localizedDescription }
      if let identity = image.macID, let api = store.api {
        _ = try? await api.rpc("images.remove", ["project": .string(draft.project), "id": .string(identity)], key: UUID().uuidString)
      }
    }
  }
}
