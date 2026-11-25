<template>
  <div class="inline-composer" :style="{ '--composer-lines': rows }">
    <span ref="referenceIcons" hidden aria-hidden="true"><el-icon><SkillIcon /></el-icon><el-icon><Document /></el-icon><el-icon><Close /></el-icon></span>
    <div ref="host"></div>
    <div v-if="nounSuggestions" :id="nounMenuId" class="composer-noun-menu" role="listbox" aria-label="名词联想" @mousedown.prevent>
      <div class="composer-noun-heading">名词联想</div>
      <div ref="nounList" class="composer-noun-list">
        <button
          v-for="(noun, index) in nounSuggestions.options"
          :id="`${nounMenuId}-${index}`"
          :key="noun"
          type="button"
          role="option"
          :aria-selected="index === nounActiveIndex"
          :class="{ active: index === nounActiveIndex }"
          @click="selectNoun(noun)"
        >{{ noun }}</button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onBeforeUnmount, onMounted, ref, useId, watch } from 'vue'
import { Compartment, EditorState, Prec } from '@codemirror/state'
import { Decoration, EditorView, WidgetType, keymap, placeholder as editorPlaceholder } from '@codemirror/view'
import { defaultKeymap, history, historyKeymap, insertNewline } from '@codemirror/commands'
import { ElIcon } from 'element-plus'
import { Close, Document } from '@element-plus/icons-vue'
import SkillIcon from '@/components/icons/SkillIcon.vue'

const props = defineProps({
  modelValue: { type: String, default: '' },
  placeholder: { type: String, default: '' },
  disabled: { type: Boolean, default: false },
  rows: { type: Number, default: 4 },
  references: { type: Array, default: () => [] },
  nounNames: { type: Array, default: () => [] },
  nounSuggestionsDisabled: { type: Boolean, default: false },
})
const emit = defineEmits(['update:modelValue', 'keydown', 'paste', 'blur', 'backspace-start', 'remove-reference'])
const host = ref(null)
const referenceIcons = ref(null)
const referencesConfig = new Compartment()
const editableConfig = new Compartment()
const placeholderConfig = new Compartment()
const nounMenuId = `noun-suggestions-${useId()}`
const nounList = ref(null)
const nounSuggestions = ref(null)
const nounActiveIndex = ref(-1)
const suggestNouns = computed(() => () => null)
let composing = false
let view
let focusPending = false
const focus = () => {
  focusPending = true
  if (!view || props.disabled) return
  view.focus()
  focusPending = false
}

const closeNounSuggestions = () => { nounSuggestions.value = null; nounActiveIndex.value = -1 }
const updateNounSuggestions = () => {
  const selection = view?.state.selection.main
  nounActiveIndex.value = -1
  nounSuggestions.value = view?.hasFocus && !props.disabled && !props.nounSuggestionsDisabled
    && !composing && !view.composing && selection?.empty
    ? suggestNouns.value(view.state.doc.toString(), selection.head)
    : null
}
const selectNoun = noun => {
  if (!view || !nounSuggestions.value || props.disabled) return
  const { from, to } = nounSuggestions.value
  view.dispatch({ changes: { from, to, insert: noun }, selection: { anchor: from + noun.length }, userEvent: 'input.complete' })
  closeNounSuggestions()
  view.focus()
}
const handleNounKeydown = event => {
  if (!nounSuggestions.value || event.shiftKey || event.ctrlKey || event.metaKey || event.altKey) return false
  const options = nounSuggestions.value.options
  if (event.key === 'ArrowDown' || event.key === 'ArrowUp') {
    event.preventDefault()
    nounActiveIndex.value = nounActiveIndex.value < 0
      ? (event.key === 'ArrowDown' ? 0 : options.length - 1)
      : (nounActiveIndex.value + (event.key === 'ArrowDown' ? 1 : -1) + options.length) % options.length
    nextTick(() => nounList.value?.querySelector('.active')?.scrollIntoView({ block: 'nearest' }))
    return true
  }
  if (event.key === 'Enter' || event.key === 'Tab') {
    if (nounActiveIndex.value < 0) {
      closeNounSuggestions()
      return false
    }
    event.preventDefault()
    selectNoun(options[nounActiveIndex.value])
    return true
  }
  if (event.key === 'Escape') {
    event.preventDefault()
    closeNounSuggestions()
    return true
  }
  return false
}
watch([nounSuggestions, nounActiveIndex], () => {
  if (!view) return
  view.contentDOM.setAttribute('aria-autocomplete', 'list')
  if (nounSuggestions.value) {
    view.contentDOM.setAttribute('aria-controls', nounMenuId)
  } else {
    view.contentDOM.removeAttribute('aria-controls')
  }
  if (nounSuggestions.value && nounActiveIndex.value >= 0) {
    view.contentDOM.setAttribute('aria-activedescendant', `${nounMenuId}-${nounActiveIndex.value}`)
  } else {
    view.contentDOM.removeAttribute('aria-activedescendant')
  }
})

class ReferencesWidget extends WidgetType {
  constructor(references) { super(); this.references = references }
  toDOM() {
    const dom = document.createElement('span')
    dom.className = 'composer-reference-prefix'
    // Keep Vue rendering outside CodeMirror updates to avoid reentrant watchers.
    for (const chip of this.references) {
      const tag = document.createElement('span')
      tag.className = `context-chip composer-reference ${chip.type}`
      tag.title = chip.path || chip.label
      const icon = referenceIcons.value.children[chip.type === 'skill' ? 0 : 1].cloneNode(true)
      icon.classList.add('chip-icon')
      const label = document.createElement('span')
      label.className = 'chip-label'
      label.textContent = chip.label
      const remove = document.createElement('button')
      remove.type = 'button'
      remove.className = 'reference-remove'
      remove.setAttribute('aria-label', `移除${chip.label}`)
      remove.disabled = props.disabled
      remove.append(referenceIcons.value.children[2].cloneNode(true))
      remove.addEventListener('click', () => { emit('remove-reference', chip); view.focus() })
      tag.append(icon, label, remove)
      dom.append(tag)
    }
    // A real inline spacer keeps the native caret beyond the tag, unlike a trailing margin.
    const spacer = document.createElement('span')
    spacer.className = 'composer-reference-spacer'
    spacer.setAttribute('aria-hidden', 'true')
    spacer.textContent = '\u00a0'
    dom.append(spacer)
    return dom
  }
}
const referenceExtension = () => EditorView.decorations.of(Decoration.set(props.references.length
  ? [Decoration.widget({ widget: new ReferencesWidget(props.references), side: -1 }).range(0)] : []))
const placeholderExtension = () => [
  editorPlaceholder(props.placeholder),
  EditorView.contentAttributes.of({ 'aria-label': props.placeholder, placeholder: props.placeholder }),
]
const createState = doc => EditorState.create({
  doc,
  selection: { anchor: doc.length },
  extensions: [
    EditorView.lineWrapping, history(),
    keymap.of([{ key: 'Shift-Enter', run: insertNewline }, ...historyKeymap, ...defaultKeymap]),
    referencesConfig.of(referenceExtension()),
    editableConfig.of(EditorView.editable.of(!props.disabled)),
    placeholderConfig.of(placeholderExtension()),
    Prec.highest(EditorView.domEventHandlers({
      keydown(event, editor) {
        if (props.disabled) return true
        if (composing || event.isComposing || editor.composing || event.keyCode === 229) return false
        if (handleNounKeydown(event)) return true
        if (event.key === 'Backspace' && !event.isComposing && !editor.composing
          && editor.state.selection.main.empty && editor.state.selection.main.from === 0) emit('backspace-start', event)
        emit('keydown', event)
        return event.defaultPrevented
      },
      paste(event) { emit('paste', event); return event.defaultPrevented },
      blur(event) { closeNounSuggestions(); emit('blur', event); return false },
      compositionstart() { composing = true; closeNounSuggestions(); return false },
      compositionend() {
        composing = false
        requestAnimationFrame(() => { if (view && !view.destroyed) updateNounSuggestions() })
        return false
      },
    })),
    EditorView.updateListener.of(update => {
      if (update.docChanged) emit('update:modelValue', update.state.doc.toString())
      if (update.docChanged || update.selectionSet) updateNounSuggestions()
    }),
  ],
})
onMounted(() => {
  view = new EditorView({ parent: host.value, state: createState(props.modelValue) })
  if (focusPending) focus()
})
watch(() => props.modelValue, value => {
  // External drafts must not carry undo history from a different conversation.
  if (view && view.state.doc.toString() !== value) {
    closeNounSuggestions()
    view.setState(createState(value))
  }
})
watch(() => [props.references, props.disabled], () => {
  if (view) view.dispatch({ effects: [referencesConfig.reconfigure(referenceExtension()), editableConfig.reconfigure(EditorView.editable.of(!props.disabled))] })
})
watch(() => props.placeholder, () => {
  if (view) view.dispatch({ effects: placeholderConfig.reconfigure(placeholderExtension()) })
})
watch(() => props.disabled, disabled => {
  if (disabled) closeNounSuggestions()
  if (!disabled && focusPending) nextTick(focus)
}, { flush: 'post' })
watch([suggestNouns, () => props.nounSuggestionsDisabled], updateNounSuggestions)
onBeforeUnmount(() => view?.destroy())
defineExpose({
  focus,
  containsTarget: target => !!target && !!host.value?.contains(target),
})
</script>

<style scoped>
.inline-composer { position: relative; min-width: 0; color: #303133; font-size: calc(14px + var(--workspace-font-size-offset, 0px)); line-height: 21px; }
.composer-noun-menu { position: absolute; z-index: 20; left: 0; bottom: calc(100% + 8px); width: min(360px, 100%); border: 1px solid #d8dade; border-radius: 10px; background: #fff; box-shadow: 0 10px 28px rgba(31, 35, 41, .16); overflow: hidden; }
.composer-noun-heading { padding: 7px 12px; color: #8b929a; font-size: calc(11px + var(--workspace-font-size-offset, 0px)); }
.composer-noun-list { max-height: min(260px, 35vh); overflow-y: auto; }
.composer-noun-list button { display: block; width: 100%; padding: 8px 12px; border: 0; background: transparent; color: #30343a; text-align: left; font: inherit; overflow-wrap: anywhere; cursor: pointer; }
.composer-noun-list button:hover, .composer-noun-list button.active { background: #f3f5f7; }
.inline-composer :deep(.cm-editor) { min-height: calc(var(--composer-lines) * 21px + 14px); outline: none; }
.inline-composer :deep(.cm-scroller) { max-height: min(280px, 40dvh); font: inherit; line-height: 21px; overflow: auto; scrollbar-width: thin; }
.inline-composer :deep(.cm-content) { padding: 7px 0; overflow-wrap: anywhere; }
.inline-composer :deep(.cm-line) { padding: 0 6px; }
.inline-composer :deep(.cm-placeholder) { color: #a8abb2; }
.inline-composer :deep(.composer-reference) { display: inline-flex; align-items: center; gap: 4px; height: 24px; margin-right: 12px; max-width: min(240px, 100%); padding: 0 8px; border-radius: 6px; box-sizing: border-box; font-size: calc(12px + var(--workspace-font-size-offset, 0px)); vertical-align: top; }
.inline-composer :deep(.composer-reference.skill) { background: #ecf5ff; color: #409eff; }
.inline-composer :deep(.composer-reference:nth-last-child(2)) { margin-right: 0; }
.inline-composer :deep(.composer-reference-spacer) { display: inline-block; width: 12px; height: 21px; vertical-align: top; }
.inline-composer :deep(.composer-reference.file) { background: #e8f4e8; color: #2e7d32; }
.inline-composer :deep(.chip-label) { min-width: 0; max-width: 180px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.inline-composer :deep(.chip-icon) { flex: 0 0 14px; width: 14px; height: 14px; }
.inline-composer :deep(.reference-remove) { display: inline-flex; align-items: center; justify-content: center; flex: 0 0 18px; width: 18px; height: 18px; padding: 0; border: 0; border-radius: 3px; color: inherit; background: transparent; cursor: pointer; }
.inline-composer :deep(.reference-remove:hover) { background: rgba(0, 0, 0, .06); }
.inline-composer :deep(.reference-remove:focus-visible) { outline: 2px solid #409eff; outline-offset: 1px; }
</style>
