<template>
  <section class="content-renderer">
    <template v-for="(segment, index) in segments" :key="`${segment.type}-${index}`">
      <div
        v-if="segment.type === 'markdown'"
        class="markdown-body"
        v-html="renderSegment(segment.source)"
      />
      <HtmlPreviewCard v-else :content="segment.source" :view-only="viewOnly" />
    </template>
  </section>
</template>

<script setup>
import { computed } from 'vue'
import { parseContentSegments } from '@/utils/content-format'
import { renderMarkdown, renderStreamingMarkdown } from '@/utils/markdown'
import HtmlPreviewCard from './HtmlPreviewCard.vue'

const props = defineProps({
  content: { type: String, default: '' },
  streaming: { type: Boolean, default: false },
  viewOnly: { type: Boolean, default: false },
  htmlPreviewEnabled: { type: Boolean, default: true },
})

const segments = computed(() => (
  props.streaming || !props.htmlPreviewEnabled
    ? [{ type: 'markdown', source: props.content }]
    : parseContentSegments(props.content)
))

const renderSegment = source => (
  props.streaming ? renderStreamingMarkdown(source) : renderMarkdown(source)
)
</script>

<style scoped>
.content-renderer {
  min-width: 0;
  color: #1f2328;
  font-size: calc(14px + var(--workspace-font-size-offset, 0px));
  line-height: 1.6;
}

.markdown-body {
  min-width: 0;
  overflow-wrap: anywhere;
}

.markdown-body :deep(> :first-child) { margin-top: 0; }
.markdown-body :deep(> :last-child) { margin-bottom: 0; }
.markdown-body :deep(p) { margin: 8px 0; }
.markdown-body :deep(h1),
.markdown-body :deep(h2),
.markdown-body :deep(h3),
.markdown-body :deep(h4),
.markdown-body :deep(h5),
.markdown-body :deep(h6) {
  margin: 20px 0 8px;
  color: #1f2328;
  font-weight: 600;
  line-height: 1.3;
  letter-spacing: 0;
}
.markdown-body :deep(h1) { padding-bottom: 8px; border-bottom: 1px solid #d1d9e0; font-size: calc(22px + var(--workspace-font-size-offset, 0px)); }
.markdown-body :deep(h2) { padding-bottom: 6px; border-bottom: 1px solid #d1d9e0; font-size: calc(19px + var(--workspace-font-size-offset, 0px)); }
.markdown-body :deep(h3) { font-size: calc(16px + var(--workspace-font-size-offset, 0px)); }
.markdown-body :deep(h4), .markdown-body :deep(h5), .markdown-body :deep(h6) { font-size: calc(14px + var(--workspace-font-size-offset, 0px)); }

.markdown-body :deep(ul), .markdown-body :deep(ol) { margin: 8px 0; padding-left: 24px; }
.markdown-body :deep(li) { margin: 3px 0; }
.markdown-body :deep(li > p) { margin: 3px 0; }
.markdown-body :deep(input[type='checkbox']) { margin: 0 7px 0 -20px; vertical-align: middle; }
.markdown-body :deep(blockquote) {
  margin: 10px 0;
  padding: 0 14px;
  border-left: 4px solid #d1d9e0;
  color: #59636e;
}
.markdown-body :deep(blockquote > :first-child) { margin-top: 0; }
.markdown-body :deep(blockquote > :last-child) { margin-bottom: 0; }
.markdown-body :deep(hr) { height: 2px; margin: 18px 0; border: 0; background: #d1d9e0; }
.markdown-body :deep(a) { color: #0969da; text-decoration: none; }
.markdown-body :deep(a:hover) { text-decoration: underline; }
.markdown-body :deep(a.noun-explanation-link),
.markdown-body :deep(a.noun-explanation-link:visited),
.markdown-body :deep(a.noun-explanation-link:hover),
.markdown-body :deep(a.noun-explanation-link:active) {
  color: #0969da;
  background: rgba(9, 105, 218, 0.07);
  border-radius: 3px;
  display: inline-block;
  margin: 0 0.12em;
  padding: 0.06em 0.12em;
}
.markdown-body :deep(strong) { font-weight: 600; }
.markdown-body :deep(img) { display: block; max-width: 100%; height: auto; margin: 10px 0; border-radius: 6px; }

.markdown-body :deep(code) {
  padding: 2px 5px;
  border-radius: 6px;
  color: inherit;
  background: rgba(175, 184, 193, 0.2);
  font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', monospace;
  font-size: calc(0.88em + var(--workspace-font-size-offset, 0px) * 0.12);
}
.markdown-body :deep(pre) {
  max-width: 100%;
  margin: 10px 0;
  padding: 13px 15px;
  overflow: auto;
  border-radius: 6px;
  background: #f6f8fa;
  line-height: 1.55;
}
.markdown-body :deep(pre code) { padding: 0; color: inherit; background: transparent; font-size: calc(13px + var(--workspace-font-size-offset, 0px)); }
.markdown-body :deep(pre.markdown-plain-fallback) {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.markdown-body :deep(.markdown-table-wrap) {
  max-width: 100%;
  margin: 12px 0;
  overflow-x: auto;
  border: 1px solid #d8dee4;
  border-radius: 6px;
}
.markdown-body :deep(.markdown-table-wrap:focus-visible) {
  outline: 2px solid #79a8d8;
  outline-offset: 2px;
}
.markdown-body :deep(table) {
  width: 100%;
  min-width: 520px;
  border-spacing: 0;
  border-collapse: collapse;
  font-size: calc(13px + var(--workspace-font-size-offset, 0px));
}
.markdown-body :deep(th), .markdown-body :deep(td) {
  min-width: 96px;
  padding: 8px 12px;
  border-right: 1px solid #d8dee4;
  border-bottom: 1px solid #d8dee4;
  text-align: left;
  vertical-align: top;
}
.markdown-body :deep(th:last-child), .markdown-body :deep(td:last-child) { border-right: 0; }
.markdown-body :deep(tbody tr:last-child td) { border-bottom: 0; }
.markdown-body :deep(th) { color: #24292f; background: #eef2f6; font-weight: 650; }
.markdown-body :deep(tr:nth-child(even) td) { background: #f8fafc; }

</style>
