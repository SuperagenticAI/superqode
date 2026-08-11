# Deployment incident

The release dashboard marked `billing` healthy after a retry failed. It also
showed two rows for `worker` because the delivery system replayed an event.
`web` completed successfully but exceeded the release-health latency limit.

Operations confirmed that the feed order cannot be trusted: collectors buffer
events during network interruptions and append them later. Attempt number and
timestamp therefore have to drive selection; line position is not an ordering
guarantee.

