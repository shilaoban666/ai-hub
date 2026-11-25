<template>
  <div class="chat-history-skeleton" role="status" aria-label="正在加载对话" aria-busy="true">
    <div v-for="turn in 2" :key="turn" class="skeleton-turn" aria-hidden="true">
      <div class="skeleton-user"><span class="skeleton-line" /></div>
      <div class="skeleton-assistant">
        <div class="skeleton-identity"><span class="skeleton-avatar" /><span class="skeleton-name" /></div>
        <div class="skeleton-paragraph"><span /><span /><span /></div>
        <div v-if="turn === 1" class="skeleton-paragraph skeleton-paragraph-short"><span /><span /></div>
      </div>
    </div>
  </div>
</template>

<style scoped>
.chat-history-skeleton { width: 100%; padding-top: 8px; animation: history-breathe 1.8s ease-in-out infinite; }
.skeleton-turn + .skeleton-turn { margin-top: 40px; }
.skeleton-user { display: flex; align-items: center; width: 42%; min-width: 128px; height: 44px; margin: 0 0 28px auto; padding: 0 16px; box-sizing: border-box; border-radius: 6px; background: #f4f5f7; }
.skeleton-line { display: block; width: 78%; height: 10px; border-radius: 3px; background: #e8ebef; }
.skeleton-identity { display: flex; align-items: center; gap: 9px; margin-bottom: 18px; }
.skeleton-avatar { width: 22px; height: 22px; border-radius: 50%; background: #e3e7ec; }
.skeleton-name { width: 64px; height: 10px; border-radius: 3px; background: #e8ebef; }
.skeleton-paragraph { display: grid; gap: 12px; margin-bottom: 22px; }
.skeleton-paragraph span { width: 92%; height: 10px; border-radius: 3px; background: #edf0f3; }
.skeleton-paragraph span:nth-child(2) { width: 100%; }
.skeleton-paragraph span:last-child { width: 62%; }
.skeleton-paragraph-short span:first-child { width: 84%; }
.skeleton-paragraph-short span:last-child { width: 48%; }
.skeleton-turn:last-child { opacity: .65; }
@keyframes history-breathe { 0%, 100% { opacity: 1; } 50% { opacity: .55; } }
@media (max-width: 600px) { .skeleton-user { width: 64%; } .skeleton-turn + .skeleton-turn { margin-top: 28px; } }
@media (prefers-reduced-motion: reduce) { .chat-history-skeleton { animation: none; } }
</style>
