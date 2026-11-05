import Foundation
import Combine

/// Read-only inline review. Scope never silently falls back to the live project.
@MainActor final class WorkbenchReview: ObservableObject {
  @Published private(set) var listing: ReviewListing?
  @Published private(set) var document: ReviewDocument?
  @Published private(set) var failure = ""
  @Published private(set) var loading = false
  @Published private(set) var loadingFile = false
  private var generation = 0
  private var fileGeneration = 0
  private var requestedFile = ""
  private var project = ""
  private var job = ""
  private var scope: ReviewScope = .turn

  func reset() {
    generation += 1; fileGeneration += 1
    listing = nil; document = nil; failure = ""; loading = false; loadingFile = false; requestedFile = ""
  }

  func load(engine: Engine, project: String, job: String, scope: ReviewScope) async {
    generation += 1; fileGeneration += 1
    let ticket = generation
    self.project = project; self.job = job; self.scope = scope
    listing = nil; document = nil; failure = ""; loadingFile = false; requestedFile = ""
    guard !project.isEmpty, scope != .turn || !job.isEmpty else { loading = false; return }
    loading = true
    defer { if ticket == generation { loading = false } }
    do {
      let result = try await engine.call("review.list", ["project": project, "job": job, "scope": scope.rawValue])
      guard ticket == generation, !Task.isCancelled else { return }
      let next: ReviewListing = try await prepareReview(result, decode: decodeReview)
      guard ticket == generation, !Task.isCancelled else { return }
      guard next.scope == scope else { throw EngineError(message: "The review scope changed. Refresh to continue.") }
      listing = next
      if let file = next.files.first { await select(file.id, engine: engine) }
    } catch { if ticket == generation, !Task.isCancelled { failure = error.localizedDescription } }
  }

  func select(_ id: String, engine: Engine) async {
    guard let file = listing?.files.first(where: { $0.id == id }) else { return }
    guard !failure.isEmpty || (document?.id != id && !(loadingFile && requestedFile == id)) else { return }
    fileGeneration += 1
    requestedFile = id
    let fileTicket = fileGeneration; let ticket = generation
    document = nil; failure = ""; loadingFile = true
    defer { if ticket == generation, fileTicket == fileGeneration { loadingFile = false; requestedFile = "" } }
    do {
      let result = try await engine.call("review.diff", ["project": project, "job": job, "scope": scope.rawValue, "file_id": id])
      guard ticket == generation, fileTicket == fileGeneration, !Task.isCancelled else { return }
      let next = try await prepareReview(result, decode: ReviewDocument.decode)
      guard ticket == generation, fileTicket == fileGeneration, !Task.isCancelled else { return }
      guard next.id == file.id, next.path == file.path, next.scope == scope else {
        throw EngineError(message: "The review revision changed. Refresh to continue.")
      }
      document = next
    } catch { if ticket == generation, fileTicket == fileGeneration, !Task.isCancelled { failure = error.localizedDescription } }
  }
}
