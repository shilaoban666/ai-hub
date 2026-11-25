import { RUNTIME_INFO } from './runtimes.js'

export const MODEL_PROTOCOL_INFO = {
  'openai-completions': {
    label: 'OpenAI Chat Completions',
    shortLabel: 'OpenAI',
  },
  'anthropic-messages': {
    label: 'Anthropic Messages',
    shortLabel: 'Anthropic',
  },
}

export const MODEL_PROTOCOL_OPTIONS = Object.entries(MODEL_PROTOCOL_INFO).map(
  ([value, info]) => ({ value, label: info.label }),
)

export const getModelProtocolLabel = (protocol, short = false) => {
  const info = MODEL_PROTOCOL_INFO[protocol]
  if (!info) return '未配置'
  return short ? info.shortLabel : info.label
}

export const isModelCompatibleWithRuntime = (model, runtimeType) => {
  if (Array.isArray(model?.compatible_runtimes)) {
    return model.compatible_runtimes.includes(runtimeType)
  }
  return (RUNTIME_INFO[runtimeType]?.model_protocols || []).includes(model?.api_protocol)
}

const RUNTIME_PROTOCOL_PRIORITY = {
  claude_code: ['anthropic-messages'],
}

export const getCompatibleModelsForRuntime = (models, runtimeType) => {
  const priorities = RUNTIME_PROTOCOL_PRIORITY[runtimeType] || []
  return (models || [])
    .filter(model => isModelCompatibleWithRuntime(model, runtimeType))
    .map((model, index) => ({ model, index }))
    .sort((left, right) => {
      const leftPriority = priorities.indexOf(left.model?.api_protocol)
      const rightPriority = priorities.indexOf(right.model?.api_protocol)
      const normalizedLeft = leftPriority === -1 ? priorities.length : leftPriority
      const normalizedRight = rightPriority === -1 ? priorities.length : rightPriority
      return normalizedLeft - normalizedRight || left.index - right.index
    })
    .map(item => item.model)
}

export const getModelOptionLabel = model => {
  const source = [model?.provider, model?.remarks].filter(Boolean).join(' · ')
  return source ? `${model?.name || ''} (${source})` : (model?.name || '')
}

export const getModelGroupsForRuntime = (models, runtimeType) => {
  const available = getCompatibleModelsForRuntime(models, runtimeType)
  return [
    { key: 'platform', label: '平台模型', models: available.filter(model => model.scope === 'platform') },
    { key: 'user', label: '自定义模型', models: available.filter(model => model.scope !== 'platform') },
  ].filter(group => group.models.length)
}

export const getModelOptionMeta = model => [
  model?.scope === 'platform' ? '平台' : null,
  model?.provider,
  model?.remarks,
  getModelProtocolLabel(model?.api_protocol, true),
].filter(Boolean).join(' · ')
