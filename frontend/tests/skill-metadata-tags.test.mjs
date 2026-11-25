import test from 'node:test'
import assert from 'node:assert/strict'
import { addSkillMetadataTags, parseSkillMetadataTags } from '../src/utils/skill-metadata-tags.js'

test('legacy module and role strings render as unique tags without splitting spaces', () => {
  assert.deepEqual(parseSkillMetadataTags('  订单,物流，订单;客服；研发\n数据\r\n  '), ['订单', '物流', '客服', '研发', '数据'])
  assert.deepEqual(parseSkillMetadataTags('产品 设计'), ['产品 设计'])
  assert.deepEqual(parseSkillMetadataTags(null), [])
  assert.deepEqual(parseSkillMetadataTags(' ,；\n '), [])
})

test('adding typed tags preserves existing values and uses the compatible storage format', () => {
  assert.equal(addSkillMetadataTags('订单，物流', '  物流,新品研发；采购  '), '订单,物流,新品研发,采购')
  assert.equal(addSkillMetadataTags('', '新品研发'), '新品研发')
  assert.equal(addSkillMetadataTags('物流', ' \n '), '物流')
})
