// Persist these short IDs in the existing icon field; versioned assets keep
// published characters stable as future illustrations are added.
export const ASSISTANT_CHARACTERS = Object.freeze([
  { id: '@cow', name: '小牛', src: '/characters/cow-v1.svg' },
  { id: '@sprout', name: '小树苗', src: '/characters/sprout-v1.svg' },
])

export function getAssistantCharacter(icon) {
  return ASSISTANT_CHARACTERS.find(item => item.id === icon?.trim()) || null
}

export function getAssistantImage(icon) {
  return getAssistantCharacter(icon)?.src || (/^\/uploads\/images\/[A-Za-z0-9_-]+\.(png|jpe?g|gif|webp|ico|svg)$/i.test(icon || '') ? icon : '')
}
