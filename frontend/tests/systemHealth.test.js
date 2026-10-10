import assert from 'node:assert/strict'
import test from 'node:test'
import { systemHealthLabel } from '../src/systemHealth.js'

test('system status reflects the real backend health result', () => {
  assert.equal(systemHealthLabel('loading', null), 'CHECKING')
  assert.equal(systemHealthLabel('error', null), 'OFFLINE')
  assert.equal(systemHealthLabel('success', { status: 'online' }), 'OPERATIONAL')
  assert.equal(systemHealthLabel('success', { status: 'degraded' }), 'DEGRADED')
  assert.equal(systemHealthLabel('success', null), 'DEGRADED')
})
