<template>
  <div class="identity-shell">
    <header class="identity-header">
      <div class="identity-brand" aria-label="AI Hub">
        <span class="brand-mark">
          <Connection />
        </span>
        <span class="brand-copy">
          <strong>AI Hub</strong>
          <span>AI Hub</span>
        </span>
      </div>
    </header>

    <main class="identity-main">
      <section class="identity-panel" :class="{ 'is-compact': compact }">
        <slot />
      </section>
    </main>

    <footer class="identity-footer">统一身份认证</footer>
  </div>
</template>

<script setup>
import { Connection } from '@element-plus/icons-vue'

defineProps({
  compact: {
    type: Boolean,
    default: false,
  },
})
</script>

<style scoped>
.identity-shell {
  --identity-ink: #1f2937;
  --identity-muted: #667085;
  --identity-border: #dde3ec;
  --identity-primary: #315efb;
  min-height: 100vh;
  min-height: 100dvh;
  display: grid;
  grid-template-rows: 72px minmax(0, 1fr) 56px;
  color: var(--identity-ink);
  background: #f6f8fc;
  font-family: Inter, "PingFang SC", "Microsoft YaHei", system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
}

.identity-header {
  display: flex;
  align-items: center;
  padding: 0 36px;
}

.identity-brand {
  display: inline-flex;
  align-items: center;
  gap: 10px;
}

.brand-mark {
  width: 32px;
  height: 32px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  flex: 0 0 auto;
  color: #fff;
  background: var(--identity-primary);
  border-radius: 7px;
}

.brand-mark :deep(svg) {
  width: 18px;
  height: 18px;
}

.brand-copy {
  display: flex;
  align-items: baseline;
  gap: 6px;
  line-height: 1;
}

.brand-copy strong {
  font-size: 15px;
  font-weight: 700;
}

.brand-copy span {
  color: var(--identity-muted);
  font-size: 13px;
}

.identity-main {
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
}

.identity-panel {
  width: min(100%, 400px);
  padding: 38px 40px 32px;
  background: #fff;
  border: 1px solid var(--identity-border);
  border-radius: 8px;
  box-shadow: 0 16px 40px rgba(39, 53, 85, 0.08);
}

.identity-panel.is-compact {
  width: min(100%, 360px);
}

.identity-footer {
  display: flex;
  align-items: center;
  justify-content: center;
  color: #8b95a7;
  font-size: 12px;
}

@media (max-width: 640px) {
  .identity-shell {
    grid-template-rows: 64px minmax(0, 1fr) 44px;
  }

  .identity-header {
    padding: 0 20px;
  }

  .identity-main {
    align-items: flex-start;
    padding: 38px 16px 20px;
  }

  .identity-panel {
    padding: 32px 24px 28px;
  }
}
</style>
