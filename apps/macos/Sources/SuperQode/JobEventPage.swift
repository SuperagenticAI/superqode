import Foundation

/// Activity paging is independent of run status: completed runs can still have unread pages.
struct JobEventPage {
  let events: [[String: Any]]
  let nextSequence: Int
  let hasMore: Bool
  let streamOpen: Bool

  init(_ record: [String: Any], after: Int) throws {
    guard let incoming = record["events"] as? [[String: Any]], incoming.count <= 500 else {
      throw JobEventPageError()
    }
    var sequence = after
    for event in incoming {
      guard let next = event["sequence"] as? Int, next > sequence else {
        throw JobEventPageError()
      }
      sequence = next
    }
    if let declared = record["next_sequence"], (declared as? Int) != sequence {
      throw JobEventPageError()
    }
    // Older bundled engines do not provide explicit continuation metadata.
    let more = record["has_more_events"] as? Bool ?? (incoming.count == 500)
    guard !more || sequence > after else { throw JobEventPageError() }
    events = incoming
    nextSequence = sequence
    hasMore = more
    streamOpen = record["event_stream_open"] as? Bool ?? false
  }
}

private struct JobEventPageError: LocalizedError {
  var errorDescription: String? {
    "The local engine returned an invalid activity page. Reopen the conversation to retry."
  }
}
