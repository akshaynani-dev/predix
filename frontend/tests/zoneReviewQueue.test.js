import test from 'node:test'
import assert from 'node:assert/strict'
import { rankZoneReviewCues } from '../src/zoneReviewQueue.js'

test('zone review cues sort by configured rule category and then by name', () => {
  const zones = [
    { zone_id: 'z', name: 'Zulu', security_attention: { status: 'capacity_review' } },
    { zone_id: 'b', name: 'Beta', security_attention: { status: 'priority_review' } },
    { zone_id: 'a', name: 'Alpha', security_attention: { status: 'priority_review' } },
    { zone_id: 'n', name: 'No trigger', security_attention: { status: 'no_configured_trigger' } },
    { zone_id: 'i', name: 'Unknown', security_attention: { status: 'insufficient_data' } },
  ]

  assert.deepEqual(rankZoneReviewCues(zones).map((zone) => zone.zone_id), ['a', 'b', 'z'])
  assert.deepEqual(zones.map((zone) => zone.zone_id), ['z', 'b', 'a', 'n', 'i'])
})

test('missing zone summaries do not create a review cue', () => {
  assert.deepEqual(rankZoneReviewCues(null), [])
  assert.deepEqual(rankZoneReviewCues([{ zone_id: 'a', name: 'Alpha' }]), [])
})
