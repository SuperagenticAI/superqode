import Foundation

@MainActor extension Workspace {
  var currentDestination: WorkspaceDestination {
    WorkspaceDestination(
      projectID: projectID, projectPath: string(project, "path"),
      conversationID: composerConversationID, jobID: selectedJob, section: section,
      filePath: selectedFile, inspectorVisible: inspectorVisible,
      checkpointID: checkpointID, checkpointPath: checkpointPath, showWelcome: showWelcome,
      review: reviewSelection)
  }

  var composerKey: String {
    WorkspaceRecoverySnapshot.key(project: projectID, conversation: composerConversationID)
  }

  var composerRecovery: ComposerRecovery {
    ComposerRecovery(
      text: draft, files: contextFiles,
      images: imageAttachments.map { ["id": string($0, "id"), "name": string($0, "name")] },
      mode: interactionMode, contextWindow: contextWindow, summarize: summarizeContext,
      reviewComments: reviewCommentStore.drafts)
  }

  func migrateLegacyDraft(settings: [String: Any]) {
    guard !recoverySnapshot.migratedProjects.contains(projectID) else { return }
    let key = WorkspaceRecoverySnapshot.key(project: projectID, conversation: "")
    if recoverySnapshot.composers[key] == nil {
      let text =
        (preferences.dictionary(forKey: "nativeDrafts") as? [String: String])?[projectID]
        ?? (settings["drafts"] as? [String: String])?[projectID] ?? ""
      recoverySnapshot.composers[key] = ComposerRecovery(text: text)
    }
    // Keep the legacy source intact until a recovery snapshot has been saved.
    recoverySnapshot.migratedProjects.insert(projectID)
  }

  func restoreComposer(conversationID: String) {
    restoringComposer = true
    defer { restoringComposer = false }
    composerConversationID = conversationID
    let saved = recoverySnapshot.composers[composerKey] ?? ComposerRecovery()
    draftStore.text = saved.text
    contextFiles = saved.files
    imageAttachments = saved.images.map { $0.mapValues { $0 as Any } }
    interactionMode = saved.mode
    contextWindow = saved.contextWindow
    summarizeContext = saved.summarize
    reviewCommentStore.drafts = saved.reviewComments ?? [:]
  }

  func persistDestination() {
    guard !restoringNavigation, !openingProject, !projectID.isEmpty, !loadingConversationDraft
    else { return }
    recoverySnapshot.lastDestination = currentDestination
    recoverySnapshot.destinations[composerKey] = currentDestination
    recoverySnapshot.projectDestinations[projectID] = currentDestination
    scheduleRecoverySave()
  }

  func restoreSessionDestination() {
    let saved = recoverySnapshot.destinations[composerKey]
    selectedFile = saved?.filePath ?? ""
    inspectorVisible = saved?.inspectorVisible ?? false
    checkpointID = saved?.checkpointID ?? ""
    checkpointPath = saved?.checkpointPath ?? ""
    reviewSelection = saved?.review ?? ReviewSelection()
  }

  func recordNavigation(_ destination: WorkspaceDestination) {
    guard !restoringNavigation, !destination.projectID.isEmpty,
      navigationHistory.last != destination
    else { return }
    navigationHistory.append(destination)
    if navigationHistory.count > 100 { navigationHistory.removeFirst() }
    forwardHistory = []
  }

  func goForward() { travelHistory(forward: true) }

  func travelHistory(forward: Bool) {
    guard !openingProject, !busy, !restoringNavigation,
      let target = (forward ? forwardHistory : navigationHistory).last
    else { return }
    let previous = currentDestination
    saveDraft()
    if target.projectID == projectID {
      applyDestination(target)
      if forward {
        forwardHistory.removeLast()
        navigationHistory.append(previous)
      } else {
        navigationHistory.removeLast()
        forwardHistory.append(previous)
      }
    } else {
      // Keep the history entry until the destination has actually opened.
      restoringNavigation = true
      perform {
        do {
          try await self.restoreDestination(target)
          if forward {
            self.forwardHistory.removeLast()
            self.navigationHistory.append(previous)
          } else {
            self.navigationHistory.removeLast()
            self.forwardHistory.append(previous)
          }
        } catch { self.notice = "Couldn’t reopen this destination. " + error.localizedDescription }
      }
    }
  }

  func restoreDestination(_ destination: WorkspaceDestination) async throws {
    if !restoringNavigation { saveDraft() }
    restoringNavigation = true
    defer {
      restoringNavigation = false
      persistDestination()
    }
    guard !destination.projectPath.isEmpty else {
      throw EngineError(message: "The saved project location is unavailable.")
    }
    if projectID != destination.projectID {
      try await open(
        destination.projectPath, recordHistory: false, expectedProjectID: destination.projectID)
    }
    applyDestination(destination)
  }

  func applyDestination(_ destination: WorkspaceDestination) {
    if !restoringNavigation { saveDraft() }
    let previous = restoringNavigation
    restoringNavigation = true
    selectJob(
      destination.jobID, conversationID: destination.conversationID, recordHistory: false,
      targetSection: Sections.names.contains(destination.section)
        ? destination.section : "Workspace")
    selectedFile = destination.filePath
    inspectorVisible = destination.inspectorVisible
    checkpointID = destination.checkpointID
    checkpointPath = destination.checkpointPath
    reviewSelection = destination.review ?? ReviewSelection()
    showWelcome = destination.showWelcome
    restoringNavigation = previous
    persistDestination()
  }

  func scheduleRecoverySave() {
    recoverySaveTask?.cancel()
    recoverySaveTask = Task {
      do { try await Task.sleep(for: .milliseconds(350)) } catch { return }
      self.recoverySnapshot.editors = self.fileDrafts
      self.recoverySaveGeneration += 1
      let generation = self.recoverySaveGeneration
      self.recoveryStore.saveInBackground(self.recoverySnapshot) { [weak self] error in
        guard let self, generation == self.recoverySaveGeneration else { return }
        self.recoveryIssue =
          error.map {
            "Draft recovery could not be saved. Copy or save your edits before quitting. "
              + $0.localizedDescription
          } ?? ""
      }
    }
  }

  @discardableResult func flushRecovery() -> Bool {
    recoverySaveTask?.cancel()
    recoverySaveGeneration += 1
    recoverySnapshot.editors = fileDrafts
    do {
      try recoveryStore.save(recoverySnapshot)
      recoveryIssue = ""
      return true
    } catch {
      recoveryIssue =
        "Draft recovery could not be saved. Copy or save your edits before quitting. "
        + error.localizedDescription
      return false
    }
  }

  var recoveredFilePaths: [String] {
    let prefix = projectID + "\n"
    return fileDrafts.keys.filter { $0.hasPrefix(prefix) }.map {
      String($0.dropFirst(prefix.count))
    }.sorted()
  }

  func clearAcceptedSubmission(key: String, submitted: ComposerRecovery) {
    // A reply can arrive after navigation. Clear only the accepted payload in its
    // original draft; never clear the text or attachments of another session.
    var saved = key == composerKey ? composerRecovery : recoverySnapshot.composers[key] ?? submitted
    if saved.text == submitted.text { saved.text = "" }
    if saved.files == submitted.files { saved.files = [] }
    if saved.images == submitted.images { saved.images = [] }
    recoverySnapshot.composers[key] = saved
    flushRecovery()
  }

  func resetRecovery() {
    guard
      confirm(
        "Reset recovery storage?",
        "The unreadable saved file will be preserved under another name. Current drafts will be saved in a new recovery file.",
        button: "Preserve and reset")
    else { return }
    do {
      let archive = try recoveryStore.resetPreservingSavedFile()
      saveDraft()
      if flushRecovery() {
        notice =
          archive.map { "Previous recovery preserved at " + $0.path }
          ?? "Recovery storage is ready."
      }
    } catch { recoveryIssue = "Recovery could not be reset. " + error.localizedDescription }
  }

  func appendReviewFeedback(_ text: String, project: String, conversation: String) -> Bool {
    guard project == projectID, conversation == composerKey, !loadingConversationDraft,
      !openingProject, !restoringNavigation else {
      notice = "The selected session changed. Return to the review and add feedback again."
      return false
    }
    draft += (draft.isEmpty ? "" : "\n\n") + text
    saveDraft()
    section = "Workspace"
    notice = "Review feedback added to your draft. Review the message before sending."
    return true
  }

  func setTranscriptPosition(
    _ position: TranscriptPosition, for job: String, project: String? = nil
  ) {
    let project = project ?? projectID
    guard !project.isEmpty, !job.isEmpty else { return }
    recoverySnapshot.transcripts[
      WorkspaceRecoverySnapshot.key(project: project, conversation: job)] = position
    scheduleRecoverySave()
  }

  func transcriptPosition(for job: String) -> TranscriptPosition {
    recoverySnapshot.transcripts[
      WorkspaceRecoverySnapshot.key(project: projectID, conversation: job)] ?? .init()
  }
}
