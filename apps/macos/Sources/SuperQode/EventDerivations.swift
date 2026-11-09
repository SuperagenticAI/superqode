import Foundation

/// Values derived from the selected run's events, computed once per event
/// change. Views that re-render on every workspace update (navigation, polling)
/// read these instead of rescanning the whole event list in their bodies.
@MainActor final class EventDerivations {
  private struct Key: Equatable {
    var job: String
    var count: Int
    var first: Int?
    var last: Int?
    var status: String
  }
  private var planKey: Key?
  private var plan: [PlanItem] = []
  private var healthKey: Key?
  private var health = ProviderHealth()
  private var responseKey: Key?
  private var response = ""

  private func key(job: String, events: [[String: Any]], status: String) -> Key {
    Key(job: job, count: events.count, first: events.first?["sequence"] as? Int,
      last: events.last?["sequence"] as? Int, status: status)
  }

  func plan(job: String, events: [[String: Any]]) -> [PlanItem] {
    let next = key(job: job, events: events, status: "")
    if next != planKey {
      planKey = next
      plan = PlanSnapshot.latest(events)
    }
    return plan
  }

  func response(job: String, events: [[String: Any]]) -> String {
    let next = key(job: job, events: events, status: "")
    if next != responseKey {
      responseKey = next
      response = RunStats.responseText(events)
    }
    return response
  }

  func health(job: String, events: [[String: Any]], status: String) -> ProviderHealth {
    let next = key(job: job, events: events, status: status)
    if next != healthKey {
      healthKey = next
      health = ProviderHealth.from(events: events, status: status)
    }
    return health
  }
}

@MainActor extension Workspace {
  /// Latest agent plan for the selected run, cached per event change.
  var selectedPlan: [PlanItem] { eventDerivations.plan(job: selectedJob, events: events) }
  /// Response text recorded in the selected run's events, cached per event change.
  var selectedResponseText: String { eventDerivations.response(job: selectedJob, events: events) }
  /// Reported provider health for the selected run, cached per event change.
  var selectedProviderHealth: ProviderHealth {
    eventDerivations.health(job: selectedJob, events: events, status: string(detail, "status"))
  }
}
