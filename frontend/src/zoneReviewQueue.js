const REVIEW_ORDER = {
  priority_review: 0,
  capacity_review: 1,
  occupancy_change_review: 2,
}

export function rankZoneReviewCues(zones) {
  return (Array.isArray(zones) ? zones : [])
    .filter((zone) => Object.hasOwn(REVIEW_ORDER, zone?.security_attention?.status))
    .slice()
    .sort((left, right) => (
      REVIEW_ORDER[left.security_attention.status] - REVIEW_ORDER[right.security_attention.status]
      || String(left.name || '').localeCompare(String(right.name || ''), undefined, { sensitivity: 'base' })
    ))
}
