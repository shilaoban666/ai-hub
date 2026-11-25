import { createApp, h, ref } from 'vue'
import { MdPreview } from 'md-editor-v3'
import MarkdownEditor from '../../src/components/MarkdownEditor.vue'
import '../../src/utils/markdown-editor-config.js'
import '../../src/assets/styles/skill-markdown.css'

export function mount(source) {
  const content = ref(source)
  createApp({
    setup: () => () => h('div', [
      h(MdPreview, { id: 'preview', modelValue: content.value, class: 'skill-markdown-preview' }),
      h(MarkdownEditor, {
        id: 'editor', modelValue: content.value, class: 'skill-markdown-preview',
        'onUpdate:modelValue': value => { content.value = value },
      }),
    ]),
  }).mount('#app')
  return { set: value => { content.value = value }, get: () => content.value }
}
