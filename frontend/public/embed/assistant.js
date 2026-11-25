(function () {
  'use strict'
  var script = document.currentScript
  if (!script || window.__aihubAssistant) return
  var assistantUrl = new URL(script.dataset.aihubUrl || '/embed/chat', script.src)
  if (!/^https?:$/.test(assistantUrl.protocol)) return
  var authUrl = new URL(script.dataset.aihubAuthUrl || '/func_process_app/aihub_embed_auth/', location.href)
  if (authUrl.origin !== location.origin || authUrl.username || authUrl.password) return
  var protocol = 'aihub-embed-v1'
  // Generated from icons/assistant-core.svg; keep in sync (assistant-motion test).
  // Inline SVG uses the host timeline for smooth, reversible head motion.
  var cowMarkup = "<svg id=\"hello\" aria-hidden=\"true\" focusable=\"false\" xmlns=\"http://www.w3.org/2000/svg\" width=\"64\" height=\"64\" viewBox=\"0 0 64 64\" fill=\"none\">\n  <defs>\n    <linearGradient id=\"coat\" x1=\"24\" y1=\"12\" x2=\"42\" y2=\"44\" gradientUnits=\"userSpaceOnUse\"><stop stop-color=\"#FFFFFF\"/><stop offset=\"1\" stop-color=\"#E8EDF3\"/></linearGradient>\n    <linearGradient id=\"computer\" x1=\"23\" y1=\"34\" x2=\"40\" y2=\"49\" gradientUnits=\"userSpaceOnUse\"><stop stop-color=\"#BDDFFA\"/><stop offset=\"1\" stop-color=\"#82B9E4\"/></linearGradient>\n  <filter id=\"logo-glow\" x=\"-100%\" y=\"-100%\" width=\"300%\" height=\"300%\"><feGaussianBlur stdDeviation=\"1.4\" result=\"blur\"/><feMerge><feMergeNode in=\"blur\"/><feMergeNode in=\"SourceGraphic\"/></feMerge></filter>\n  </defs>\n  <style>\n    .head { transition:transform .6s cubic-bezier(.22,1,.36,1); transform-origin:32px 35px; transform:translateY(6px) scale(.98,.9); }\n    .face { transition:transform .6s ease; transform:translateY(2px); }\n    .eyes { transition:transform .5s ease; transform-origin:32px 25px; transform:scaleY(.55); }\n    .hoof-left { animation:type-left 1.1s ease-in-out infinite; }\n    .hoof-right { animation:type-right 1.1s ease-in-out infinite; }\n    .launcher.attentive .head { transform:translateY(0) scale(1); }\n    .launcher.attentive .face { transform:translateY(0); }\n    .launcher.attentive .eyes { transform:scaleY(1); }\n    .launcher.attentive .hoof-left,.launcher.attentive .hoof-right { animation-play-state:paused; }\n    :root:target .head { transform:translateY(0) scale(1); }\n    :root:target .face { transform:translateY(0); }\n    :root:target .eyes { transform:scaleY(1); }\n    @keyframes type-left { 0%,45%,100% { transform:translateY(0); } 22% { transform:translateY(-1.8px); } }\n    @keyframes type-right { 0%,45%,100% { transform:translateY(0); } 72% { transform:translateY(-1.8px); } }\n    @media(prefers-reduced-motion:reduce) {\n      .scene .head,.scene .face,.scene .eyes,.scene .hoof-left,.scene .hoof-right { animation:none!important;transition:none!important; }\n      .launcher.attentive .head { transform:translateY(0) scale(1); }\n      .launcher.attentive .face { transform:translateY(0); }\n    }\n  </style>\n\n  <g class=\"scene\" stroke=\"#374151\" stroke-width=\"1.8\" stroke-linecap=\"round\" stroke-linejoin=\"round\">\n    <!-- The desk and chair stay planted while the cow types and looks up. -->\n    <rect x=\"18\" y=\"29\" width=\"28\" height=\"23\" rx=\"9\" fill=\"#D5E7F5\"/>\n    <path d=\"M22 43v13c0 3 6 3 7 0l3-7 3 7c1 3 7 3 7 0V43\" fill=\"#F3F4F6\"/>\n    <path d=\"M22 55h6m8 0h6\" stroke-width=\"3\"/>\n    <path d=\"M20 44v-7c0-8 24-8 24 0v7\" fill=\"url(#coat)\"/>\n    <path d=\"m29 36 3 3 3-3\" stroke=\"#94A3B8\"/>\n    <g class=\"head\">\n      <path d=\"M21 17C15 16 15 10 18 6c0 5 3 6 6 7m16 4c6-1 6-7 3-11 0 5-3 6-6 7\" fill=\"#E5E7EB\"/>\n      <path d=\"M20 19C13 13 7 16 9 21c2 5 7 5 11 2m24-4c7-6 13-3 11 2-2 5-7 5-11 2\" fill=\"#F1F5F9\"/>\n      <path d=\"m12 19 5 2m35-2-5 2\" stroke=\"#E6BFC1\" stroke-width=\"2.6\"/>\n      <path class=\"face-outline\" d=\"M32 11C20 11 16 17 17 27c0 9 6 13 15 13s15-4 15-13c1-10-3-16-15-16Z\" fill=\"url(#coat)\"/>\n      <path d=\"M28 13c-1-3 2-6 4-6l-1 4c2-2 4-2 5-1\" fill=\"#F1F5F9\"/>\n      <g class=\"face\">\n        <g class=\"eyes\" fill=\"#202833\" stroke=\"none\">\n          <ellipse cx=\"25\" cy=\"25\" rx=\"2.5\" ry=\"3.5\"/><ellipse cx=\"39\" cy=\"25\" rx=\"2.5\" ry=\"3.5\"/>\n          <circle cx=\"25.7\" cy=\"23.9\" r=\".85\" fill=\"white\"/><circle cx=\"39.7\" cy=\"23.9\" r=\".85\" fill=\"white\"/>\n        </g>\n        <path d=\"M21 30h3m16 0h3\" stroke=\"#E8B2B8\" stroke-width=\"2.8\"/>\n        <rect x=\"23\" y=\"29\" width=\"18\" height=\"9\" rx=\"4.5\" fill=\"#F6DDE0\" stroke-width=\"1.3\"/>\n        <path d=\"M27 32v1m10-1v1\" stroke-width=\"1.7\"/>\n        <path d=\"M30 35q2 1.5 4 0\" stroke-width=\"1.2\"/>\n      </g>\n    </g>\n    <path d=\"M12 52v8m40-8v8\" stroke-width=\"2.6\"/>\n    <rect x=\"7\" y=\"48\" width=\"50\" height=\"4.5\" rx=\"2\" fill=\"#E3E8EF\"/>\n    <path class=\"hoof-left\" d=\"M23 37.5c-3.2.1-5.8 2.3-6.2 5.1-.2 1.3.6 2.3 1.8 2.5 1.2.2 2.4-.4 3-1.5l1.5-2.4 2.1 1.2 1.3-2.2Z\" fill=\"#EDF3F8\"/>\n    <path class=\"hoof-right\" d=\"M41 37.5c3.2.1 5.8 2.3 6.2 5.1.2 1.3-.6 2.3-1.8 2.5-1.2.2-2.4-.4-3-1.5l-1.5-2.4-2.1 1.2-1.3-2.2Z\" fill=\"#EDF3F8\"/>\n    <path d=\"m19 46-2-7h30l-2 7\" fill=\"url(#computer)\"/>\n    <path d=\"M19 39h26\" stroke=\"#E4F3FF\" stroke-width=\"1.2\"/>\n    <path d=\"M15 46h34l-3 3H18Z\" fill=\"#D3E9FA\"/>\n    <circle cx=\"32\" cy=\"42.5\" r=\"2.1\" fill=\"#FFFFFF\" stroke=\"none\" filter=\"url(#logo-glow)\"/>\n  </g>\n</svg>\n"
  var sproutMarkup = "<svg aria-hidden=\"true\" focusable=\"false\" xmlns=\"http://www.w3.org/2000/svg\" id=\"hello\" viewBox=\"0 0 64 64\" fill=\"none\">\n  <defs>\n    <linearGradient id=\"shell\" x1=\"23\" y1=\"16\" x2=\"44\" y2=\"57\" gradientUnits=\"userSpaceOnUse\">\n      <stop stop-color=\"#F4FFFC\"/><stop offset=\".6\" stop-color=\"#D5F8ED\"/><stop offset=\"1\" stop-color=\"#9AE5CF\"/>\n    </linearGradient>\n    <linearGradient id=\"screen\" x1=\"22\" y1=\"25\" x2=\"40\" y2=\"46\" gradientUnits=\"userSpaceOnUse\">\n      <stop stop-color=\"#304C50\"/><stop offset=\"1\" stop-color=\"#20383D\"/>\n    </linearGradient>\n  </defs>\n  <style>\n    .antenna { transform-origin: 32px 17px; animation: listen 4.8s ease-in-out infinite; }\n    .gaze { animation: curious 8.4s ease-in-out infinite; }\n    .eyes { transform-origin: 32px 33.5px; animation: blink 6s ease-in-out infinite; }\n    .hand { transform-origin: 50px 35px; }\n    .left-hand { transform-origin: 13px 36px; animation: balance 4.8s ease-in-out infinite; }\n    .launcher.attentive .hand { animation: wave 1.8s cubic-bezier(.45,0,.25,1) both; }\n    .launcher.attentive .gaze { animation: none; transform: translateY(-.7px); }\n    .launcher.attentive .antenna { animation: perk 1.2s ease-in-out both; }\n    @keyframes blink { 0%, 43%, 47%, 100% { transform: scaleY(1); } 45% { transform: scaleY(.1); } }\n    @keyframes curious {\n      0%, 18%, 52%, 100% { transform: translate(0,0); }\n      24%, 40% { transform: translate(1.3px,-.6px); }\n      68%, 80% { transform: translate(-.8px,.3px); }\n    }\n    @keyframes listen { 0%, 100% { transform: rotate(-5deg); } 50% { transform: rotate(7deg); } }\n    @keyframes balance { 0%, 100% { transform: rotate(0); } 50% { transform: rotate(9deg); } }\n    @keyframes perk { 0%, 100% { transform: rotate(0); } 28% { transform: rotate(13deg); } 62% { transform: rotate(-6deg); } }\n    @keyframes wave {\n      0%, 100% { transform: rotate(0); }\n      18% { transform: rotate(-115deg); }\n      32% { transform: rotate(-65deg); }\n      46% { transform: rotate(-115deg); }\n      60% { transform: rotate(-65deg); }\n      74% { transform: rotate(-110deg); }\n      86% { transform: rotate(-65deg); }\n    }\n    @media (prefers-reduced-motion: reduce) {\n      .antenna, .gaze, .eyes, .left-hand, .launcher.attentive .hand, .launcher.attentive .gaze, .launcher.attentive .antenna { animation: none; transform: none; }\n    }\n  </style>\n  <g class=\"antenna\">\n    <path d=\"M32 17c-1-5 0-7 3-9\" stroke=\"#335452\" stroke-width=\"2.2\" stroke-linecap=\"round\"/>\n    <path d=\"M33 7c1-4 7-4 11-1-2 5-7 6-11 3Z\" fill=\"#7BDFC0\" stroke=\"#335452\" stroke-width=\"1.8\" stroke-linejoin=\"round\"/>\n    <path d=\"m36 7 4-.5\" stroke=\"#E4FFF3\" stroke-width=\"1.5\" stroke-linecap=\"round\"/>\n  </g>\n  <path class=\"left-hand\" d=\"M14 34C10 34 4 37 4 41c0 3 3 4 5 1l5-4\" fill=\"#A5EBD8\" stroke=\"#335452\" stroke-width=\"2.1\" stroke-linejoin=\"round\"/>\n  <path class=\"body\" d=\"M32 14C46 14 54 23 54 36c0 8-4 14-10 17l-1 5c-4 1-8-2-11-5-3 3-7 6-11 5l-1-5C14 50 10 44 10 36c0-13 8-22 22-22Z\" fill=\"url(#shell)\" stroke=\"#335452\" stroke-width=\"2.2\" stroke-linejoin=\"round\"/>\n  <path d=\"M17 24c3-5 8-7 14-7\" stroke=\"#FFF\" stroke-width=\"2.8\" stroke-linecap=\"round\"/>\n  <path d=\"M49 43c-2 5-6 7-10 7\" stroke=\"#85D9C0\" stroke-width=\"2\" stroke-linecap=\"round\" opacity=\".65\"/>\n  <g class=\"hand\">\n    <path d=\"M50 34c4 0 10 3 10 7 0 3-3 4-5 1l-5-4\" fill=\"#BCEFE0\" stroke=\"#335452\" stroke-width=\"2.1\" stroke-linecap=\"round\" stroke-linejoin=\"round\"/>\n    <path d=\"m55 37 2 2\" stroke=\"#F3FFFA\" stroke-width=\"1.8\" stroke-linecap=\"round\"/>\n  </g>\n  <rect x=\"15\" y=\"24\" width=\"34\" height=\"23\" rx=\"10.5\" fill=\"url(#screen)\"/>\n  <path d=\"M20 29c1-2 3-3 6-3h12\" stroke=\"#5B7979\" stroke-width=\"1.3\" stroke-linecap=\"round\" opacity=\".65\"/>\n  <g class=\"gaze\">\n    <g class=\"eyes\">\n      <rect x=\"22\" y=\"29\" width=\"6\" height=\"9.5\" rx=\"3\" fill=\"#AAFFE4\"/>\n      <rect x=\"36\" y=\"29\" width=\"6\" height=\"9.5\" rx=\"3\" fill=\"#AAFFE4\"/>\n      <path d=\"M24 31v2m14-2v2\" stroke=\"#F2FFF9\" stroke-width=\"1.7\" stroke-linecap=\"round\"/>\n    </g>\n    <path d=\"M29.5 40c1.5 2 3.5 2 5 0\" stroke=\"#CBFFEE\" stroke-width=\"1.8\" stroke-linecap=\"round\"/>\n  </g>\n  <path d=\"M20 40h3m18 0h3\" stroke=\"#F2B8BC\" stroke-width=\"2.4\" stroke-linecap=\"round\" opacity=\".9\"/>\n  <path d=\"m30 50 2 1 2-1\" stroke=\"#6DBEA7\" stroke-width=\"1.6\" stroke-linecap=\"round\" stroke-linejoin=\"round\"/>\n</svg>\n"
  function icon(name) {
    if (name === 'assistant-core') return cowMarkup
    return '<img src="' + new URL('icons/' + name + '.svg', script.src).href + '" width="14" height="14" alt="" aria-hidden="true">'
  }

  function pageContext() {
    var url = new URL(location.href)
    url.username = ''
    url.password = ''
    Array.from(url.searchParams.keys()).forEach(function (key) {
      if (['id', 'page_id', 'function_id', 'global_function_id', 'tab'].indexOf(key) < 0) url.searchParams.delete(key)
    })
    url.hash = url.hash.indexOf('#/') === 0 ? url.hash.split('?')[0] : ''
    return { url: url.href, title: document.title.slice(0, 200) }
  }

  // Business pages inside existing frames relay their active context upwards.
  if (window.parent !== window) {
    function relay() {
      window.parent.postMessage({ protocol: protocol, type: 'business-page', context: pageContext() }, location.origin)
    }
    window.addEventListener('focus', relay)
    document.addEventListener('pointerdown', relay, { passive: true })
    window.addEventListener('hashchange', relay)
    window.addEventListener('popstate', relay)
    window.__aihubAssistant = { update: relay }
    return
  }

  var root = document.createElement('div')
  root.id = 'aihub-assistant-root'
  var shadow = root.attachShadow({ mode: 'open' })
  shadow.innerHTML = '<style>' +
    ':host{all:initial;position:fixed!important;inset:0!important;display:block!important;width:auto!important;height:auto!important;margin:0!important;padding:0!important;border:0!important;contain:strict!important;overflow:hidden!important;scrollbar-width:none!important;pointer-events:none!important;z-index:2147483000;font-family:Arial,"Microsoft YaHei",sans-serif;font-size:14px;letter-spacing:0}' +
    ':host::backdrop,.greeting::backdrop{display:none!important}:host::-webkit-scrollbar,.greeting::-webkit-scrollbar{display:none!important;width:0!important;height:0!important}' +
    '.launcher,.panel,.drag-shield{pointer-events:auto}' +
    '*{box-sizing:border-box}button{font:inherit;cursor:pointer}button:focus-visible{outline:2px solid #5786B5;outline-offset:2px}' +
    '.launcher{position:fixed;right:22px;bottom:24px;width:60px;height:60px;display:grid;place-items:center;padding:0;border:0;border-radius:0;background:transparent;filter:drop-shadow(0 2px 3px #334C6630);z-index:2147483000;transition:filter .3s ease;touch-action:none;user-select:none}' +
    '.spirit-motion>img{display:block;width:60px;height:60px;object-fit:contain;transition:transform .3s ease}.launcher.attentive .spirit-motion>img{transform:translateY(-2px)}' +
    '.spirit-motion{display:block;width:60px;height:60px;pointer-events:none}' +
    '.launcher .spirit-motion>svg{display:block;width:60px;height:60px;transform-origin:50% 70%;transform:translateY(0) rotate(0) scale(1);transition:transform .42s cubic-bezier(.22,1,.36,1)}' +
    '.launcher:active .spirit-motion>svg{transform:translateY(1px) scale(.98)}' +
    '.launcher:hover{filter:drop-shadow(0 3px 4px #334C6638)}.launcher:focus-visible{outline:2px solid #74ADE0;outline-offset:3px}' +
    '.launcher.dragging{cursor:grabbing}.launcher.dragging .spirit-motion{animation-play-state:paused}.launcher.dragging .spirit-motion>svg{transform:rotate(6deg) scale(1.03,.97)}' +
    '.greeting{position:absolute;inset:auto;left:0;top:0;margin:0;width:246px;max-width:calc(100vw - 24px);padding:14px 17px;border:1px solid #DCE9F5;border-radius:18px;background:linear-gradient(135deg,#FFFFFF,#F0F7FF);color:#536579;font-size:13px;line-height:1.7;box-shadow:0 6px 24px #334C6616;z-index:2147483000;pointer-events:none;opacity:0;visibility:hidden;transform:translateY(5px) scale(.96);transform-origin:var(--tail-x,50%) bottom;transition:opacity .2s ease,transform .25s cubic-bezier(.22,1,.36,1),visibility .2s}' +
    '.greeting{overflow:visible!important;scrollbar-width:none!important;max-height:none!important}.greeting:popover-open{position:fixed}' +
    '.greeting.visible{opacity:1;visibility:visible;transform:translateY(0) scale(1)}.greeting strong{display:block;margin-bottom:3px;font-size:14px;font-weight:600;color:#315F8C}.greeting::after{content:"";position:absolute;left:var(--tail-x,50%);bottom:-6px;width:10px;height:10px;background:#F0F7FF;border-right:1px solid #DCE9F5;border-bottom:1px solid #DCE9F5;transform:translateX(-50%) rotate(45deg)}' +
    '.greeting.below{transform-origin:var(--tail-x,50%) top}.greeting.below::after{top:-6px;bottom:auto;background:#FFFFFF;border:0;border-left:1px solid #DCE9F5;border-top:1px solid #DCE9F5}' +
    '@media(prefers-reduced-motion:reduce){.greeting{transition:none;transform:none}}' +
    '@media(prefers-reduced-motion:reduce){.spirit-motion{animation:none}.launcher .spirit-motion>svg,.launcher .spirit-motion>img{transition:none;transform:none}.launcher{transition:none}}' +
    '.drag-shield{position:fixed;inset:0;z-index:2147483647;cursor:grabbing;touch-action:none;user-select:none}' +
    '.panel{position:fixed;right:0;top:0;bottom:0;width:min(520px,100vw);background:white;border-left:1px solid #DFE6EE;box-shadow:-8px 0 32px #0002;z-index:2147483001;display:flex;flex-direction:column}' +
    '.panel{overflow:auto;overscroll-behavior:contain}.panel.wide{width:min(900px,100vw)}[hidden]{display:none!important}' +
    // Keep the iframe's scroll layout alive across close/open. Inert also keeps
    // hidden controls out of keyboard navigation without unloading the chat.
    '.panel[hidden]{display:flex!important;visibility:hidden;pointer-events:none}' +
    'header{height:48px;flex:0 0 48px;display:flex;align-items:center;gap:8px;padding:0 12px;border-bottom:1px solid #E5EAF0;color:#334155}' +
    'header strong{flex:1;font-size:14px}header button{width:32px;height:32px;flex:0 0 32px;display:inline-flex;align-items:center;justify-content:center;padding:0;border:0;border-radius:4px;background:transparent;color:#64748B}header button:hover{background:#EFF5FB}header img{display:block}' +
    'header .close:focus-visible{outline:none;background:#EFF5FB}' +
    'iframe{display:block;flex:1;width:100%;min-height:0;border:0;background:#fff}' +
    '.status{position:absolute;top:48px;left:0;right:0;padding:20px;color:#64748B;font-size:13px;background:#fff}.status button{margin-left:8px;border:0;background:transparent;color:#3D76AB}' +
    '@media(max-width:600px){.launcher{right:14px;bottom:18px}.panel{width:100vw}}' +
    '</style><button class="launcher" aria-label="打开 AI 助手" aria-describedby="aihub-greeting" aria-expanded="false"><span class="spirit-motion">' + icon('assistant-core') + '</span></button>' +
    '<div class="greeting" id="aihub-greeting" role="tooltip" hidden><strong>我是小趣，你的 AI 助手</strong>需要我帮你做点什么？</div>' +
    '<section class="panel" role="complementary" aria-label="AI 助手" hidden inert><header><strong>AI 助手</strong>' +
    '<button class="expand" title="展开面板" aria-label="展开面板" aria-pressed="false">' + icon('full-screen') + '</button>' +
    '<button class="external" title="打开 AI 工作台" aria-label="打开 AI 工作台">' + icon('monitor') + '</button>' +
    '<button class="close" title="收起助手" aria-label="收起助手">' + icon('close') + '</button></header>' +
    '<div class="status" role="status">正在连接 AI Hub...</div></section>'
  // Keep the whole widget outside the host's scrollable/ transformed layout.
  // A manual popover is non-modal; pointer events still pass through to the page.
  if (typeof root.showPopover === 'function') root.setAttribute('popover', 'manual')
  document.documentElement.appendChild(root)
  if (typeof root.showPopover === 'function') root.showPopover()
  var launcher = shadow.querySelector('.launcher')
  function setMascot(value) {
    var motion = launcher.querySelector('.spirit-motion')
    if (value === '@cow') { motion.innerHTML = cowMarkup; return }
    if (value === '@sprout') { motion.innerHTML = sproutMarkup; return }
    if (!/^\/uploads\/images\/[A-Za-z0-9_-]+\.(png|jpe?g|gif|webp|ico|svg)$/i.test(value || '')) return
    var image = document.createElement('img')
    image.alt = ''
    image.setAttribute('aria-hidden', 'true')
    image.src = new URL(value, assistantUrl.origin).href
    image.onerror = function () { motion.innerHTML = cowMarkup }
    motion.replaceChildren(image)
  }
  // Fetch only public appearance once on mount; no login or recurring polling.
  var appearanceController = new AbortController()
  var appearanceTimeout = setTimeout(function () { appearanceController.abort() }, 5000)
  fetch(new URL('/aihub/api/public/assistant-appearance', assistantUrl.origin).href, {
    credentials: 'omit', signal: appearanceController.signal,
  }).then(function (response) {
    if (!response.ok) throw new Error('Appearance unavailable')
    return response.json()
  }).then(function (value) {
    // Gateway responses wrap backend JSON in { code, message, data }.
    var appearance = value && Object.prototype.hasOwnProperty.call(value, 'code') ? value.data : value
    if (appearance) setMascot(appearance.mascot)
  }).catch(function () {
    // Keep the bundled cow when the service is unavailable or not upgraded yet.
  }).finally(function () { clearTimeout(appearanceTimeout) })
  var greeting = shadow.querySelector('.greeting')
  // A manual popover uses the browser top layer, outside the page's scrollable
  // layout and transformed ancestors. Older browsers use the contained overlay.
  var greetingTopLayer = typeof greeting.showPopover === 'function'
  if (greetingTopLayer) greeting.setAttribute('popover', 'manual')
  function positionGreeting() {
    var bounds = launcher.getBoundingClientRect()
    var width = greeting.offsetWidth
    var height = greeting.offsetHeight
    var left = Math.max(12, Math.min(document.documentElement.clientWidth - width - 12, bounds.left + bounds.width / 2 - width / 2))
    var below = bounds.top < height + 24
    greeting.classList.toggle('below', below)
    greeting.style.left = left + 'px'
    greeting.style.top = (below ? bounds.bottom + 12 : bounds.top - height - 12) + 'px'
    greeting.style.setProperty('--tail-x', Math.max(18, Math.min(width - 18, bounds.left + bounds.width / 2 - left)) + 'px')
  }
  function showGreeting(event) {
    if (launcher.hidden || launcher.classList.contains('dragging') || event?.pointerType === 'touch') return
    greeting.hidden = false
    if (greetingTopLayer && !greeting.matches(':popover-open')) greeting.showPopover()
    positionGreeting()
    greeting.classList.add('visible')
  }
  function hideGreeting() {
    greeting.classList.remove('visible')
    if (greetingTopLayer && greeting.matches(':popover-open')) greeting.hidePopover()
    greeting.hidden = true
  }
  launcher.addEventListener('pointerenter', showGreeting)
  launcher.addEventListener('pointerleave', hideGreeting)
  launcher.addEventListener('focus', showGreeting)
  launcher.addEventListener('blur', hideGreeting)
  document.addEventListener('keydown', function (event) { if (event.key === 'Escape') hideGreeting() })
  var greetingTimer = null
  function greet() {
    clearTimeout(greetingTimer)
    launcher.classList.add('attentive')
  }
  function rest() {
    clearTimeout(greetingTimer)
    greetingTimer = setTimeout(function () {
      if (!launcher.matches(':hover, :focus-visible')) launcher.classList.remove('attentive')
    }, 100)
  }
  launcher.addEventListener('pointerenter', greet)
  launcher.addEventListener('pointerleave', rest)
  launcher.addEventListener('focus', greet)
  launcher.addEventListener('blur', rest)
  var panel = shadow.querySelector('.panel')
  var status = shadow.querySelector('.status')
  var frame = null
  var context = pageContext()
  var ready = false
  var supportsPrompt = false
  var pendingPrompt = null
  var promptSequence = 0
  var timeout = null
  var timer = null
  var activeFrame = null
  var authRequestPending = false
  var drag = null
  var dragFrame = null
  var launcherPosition = null
  var positionStorageKey = 'aihub:assistant:position:v1'
  var suppressClick = false
  var narrowViewport = 560

  function placeLauncher(x, y) {
    launcherPosition = {
      x: Math.max(8, Math.min(Math.max(8, document.documentElement.clientWidth - 68), x)),
      y: Math.max(8, Math.min(Math.max(8, document.documentElement.clientHeight - 68), y)),
    }
    launcher.style.left = launcherPosition.x + 'px'
    launcher.style.top = launcherPosition.y + 'px'
    launcher.style.right = 'auto'
    launcher.style.bottom = 'auto'
  }
  try {
    var savedPosition = JSON.parse(localStorage.getItem(positionStorageKey))
    if (savedPosition && Number.isFinite(savedPosition.x) && Number.isFinite(savedPosition.y)) {
      placeLauncher(savedPosition.x, savedPosition.y)
    }
  } catch (_) { /* Storage may be unavailable; keep the default position. */ }
  function renderDrag() {
    dragFrame = null
    if (drag && drag.moved) placeLauncher(drag.x - drag.offsetX, drag.y - drag.offsetY)
  }
  function endDrag(event) {
    if (!drag || (event && event.pointerId !== undefined && event.pointerId !== drag.id)) return
    if (dragFrame !== null) cancelAnimationFrame(dragFrame)
    dragFrame = null
    if (event && event.type === 'pointerup') renderDrag()
    var ended = drag
    suppressClick = ended.moved || !event || event.type !== 'pointerup'
    drag = null
    ended.shield.remove()
    launcher.classList.remove('dragging')
    if (ended.moved && launcherPosition) {
      try { localStorage.setItem(positionStorageKey, JSON.stringify(launcherPosition)) } catch (_) { /* Dragging still works without storage. */ }
    }
    if (launcher.hasPointerCapture(ended.id)) launcher.releasePointerCapture(ended.id)
  }
  launcher.addEventListener('pointerdown', function (event) {
    if (drag || event.button !== 0 || !event.isPrimary) return
    var bounds = launcher.getBoundingClientRect()
    try { launcher.setPointerCapture(event.pointerId) } catch (_) { return }
    event.preventDefault()
    suppressClick = false
    drag = {
      id: event.pointerId, startX: event.clientX, startY: event.clientY,
      offsetX: event.clientX - bounds.left, offsetY: event.clientY - bounds.top,
      x: event.clientX, y: event.clientY, moved: false, shield: document.createElement('div'),
    }
    // Keep the release in this document even when the pointer crosses a business iframe.
    drag.shield.className = 'drag-shield'
    drag.shield.setAttribute('aria-hidden', 'true')
    shadow.appendChild(drag.shield)
  })
  window.addEventListener('pointermove', function (event) {
    if (!drag || event.pointerId !== drag.id) return
    if (event.pointerType !== 'touch' && !(event.buttons & 1)) { endDrag(event); return }
    drag.x = event.clientX
    drag.y = event.clientY
    if (!drag.moved && Math.hypot(drag.x - drag.startX, drag.y - drag.startY) < 6) return
    drag.moved = true
    hideGreeting()
    launcher.classList.add('dragging')
    event.preventDefault()
    if (dragFrame === null) dragFrame = requestAnimationFrame(renderDrag)
  }, true)
  window.addEventListener('pointerup', endDrag, true)
  window.addEventListener('pointercancel', endDrag, true)
  launcher.addEventListener('lostpointercapture', endDrag)
  launcher.addEventListener('dragstart', function (event) { event.preventDefault() })
  window.addEventListener('blur', endDrag)
  window.addEventListener('pagehide', endDrag)
  document.addEventListener('visibilitychange', function () { if (document.hidden) endDrag() })
  window.addEventListener('resize', function () {
    endDrag()
    if (!panel.hidden && document.documentElement.clientWidth < narrowViewport) close()
    if (launcherPosition) placeLauncher(launcherPosition.x, launcherPosition.y)
    if (greeting.classList.contains('visible')) positionGreeting()
  })

  function sendContext() {
    if (!frame || !ready) return
    frame.contentWindow.postMessage({ protocol: protocol, type: 'context', context: context }, assistantUrl.origin)
  }
  function sendVisibility() {
    if (!frame || !ready) return
    frame.contentWindow.postMessage({ protocol: protocol, type: 'visibility', visible: !panel.hidden && !document.hidden }, assistantUrl.origin)
  }
  function finishPrompt(error) {
    if (!pendingPrompt) return
    var completed = pendingPrompt
    pendingPrompt = null
    clearTimeout(completed.timer)
    if (error) completed.reject(new Error(error))
    else completed.resolve()
  }
  function sendPrompt() {
    if (!ready || panel.hidden || !pendingPrompt || pendingPrompt.sent) return
    if (!supportsPrompt) return finishPrompt('AI Hub 暂不支持自动发送，请更新后重试')
    pendingPrompt.sent = true
    frame.contentWindow.postMessage(pendingPrompt.message, assistantUrl.origin)
  }
  function submit(skill, prompt) {
    if (typeof skill === 'string') {
      skill = skill.trim() || null
      if (skill && /^\d+$/.test(skill)) skill = Number(skill)
    }
    if (skill == null) skill = null
    if (skill !== null && typeof skill !== 'string' && (!Number.isSafeInteger(skill) || skill <= 0)) {
      return Promise.reject(new Error('技能须为 ID 或名称'))
    }
    if (typeof prompt !== 'string' || !prompt.trim()) return Promise.reject(new Error('提示词不能为空'))
    if (pendingPrompt) return Promise.reject(new Error('已有提示词正在提交，请稍候'))
    return new Promise(function (resolve, reject) {
      var duration = 30000
      pendingPrompt = {
        message: { protocol: protocol, type: 'submit-prompt', id: ++promptSequence, skill: skill, prompt: prompt.trim(), expiresAt: Date.now() + duration },
        resolve: resolve, reject: reject, sent: false,
        timer: setTimeout(function () { finishPrompt('AI Hub 未确认收到提示词，请检查边栏后重试') }, duration),
      }
      open()
      sendPrompt()
    })
  }
  document.addEventListener('visibilitychange', sendVisibility)
  function update() {
    if (!activeFrame || !activeFrame.isConnected) {
      activeFrame = null
      context = pageContext()
    } else {
      try {
        var child = activeFrame.contentWindow
        child.__aihubAssistant?.update()
      } catch (_) { /* Cross-origin business frames need their own approved bridge. */ }
    }
    sendContext()
  }
  function loadFrame() {
    ready = false
    status.hidden = false
    status.textContent = '正在连接 AI Hub...'
    if (!frame) {
      frame = document.createElement('iframe')
      frame.title = 'AI Hub 对话'
      frame.allow = 'clipboard-write'
      frame.referrerPolicy = 'strict-origin-when-cross-origin'
      panel.appendChild(frame)
    }
    frame.src = assistantUrl.href
    clearTimeout(timeout)
    timeout = setTimeout(function () {
      if (ready) return
      status.textContent = 'AI Hub 未连接'
      if (pendingPrompt && !pendingPrompt.sent) finishPrompt('AI Hub 未连接，请重试')
      var retry = document.createElement('button')
      retry.textContent = '重试'
      retry.onclick = loadFrame
      status.appendChild(retry)
    }, 15000)
  }
  function close() {
    endDrag()
    panel.setAttribute('inert', '')
    panel.hidden = true
    sendVisibility()
    if (pendingPrompt && !pendingPrompt.sent) finishPrompt('AI Hub 边栏已关闭')
    launcher.hidden = false
    launcher.setAttribute('aria-expanded', 'false')
    clearInterval(timer)
    launcher.focus()
  }
  function open() {
    endDrag()
    hideGreeting()
    panel.hidden = false
    panel.removeAttribute('inert')
    launcher.hidden = true
    launcher.setAttribute('aria-expanded', 'true')
    if (!frame) loadFrame()
    sendVisibility()
    update()
    clearInterval(timer)
    timer = setInterval(update, 1000)
    shadow.querySelector('.close').focus()
  }
  launcher.onclick = function (event) {
    if (suppressClick && event.detail !== 0) {
      event.preventDefault()
      suppressClick = false
      return
    }
    open()
  }
  async function handleAuthRequest(data) {
    if (authRequestPending || !['status', 'authorize'].includes(data.action) || typeof data.request_id !== 'string' || !/^[A-Za-z0-9_-]{43}$/.test(data.request_id)) return
    authRequestPending = true
    var destination = frame.contentWindow
    var result
    var controller = new AbortController()
    var abortTimeout = setTimeout(function () { controller.abort() }, 8000)
    try {
      var csrfCookie = document.cookie.split('; ').find(function (value) { return value.indexOf('csrftoken=') === 0 })
      var csrfToken = csrfCookie ? decodeURIComponent(csrfCookie.slice(10)) : script.dataset.aihubCsrf
      var response = await fetch(authUrl.href, {
        method: 'POST', credentials: 'same-origin', redirect: 'error', signal: controller.signal,
        headers: { 'Content-Type': 'application/json', 'X-CSRFToken': csrfToken || '' },
        body: JSON.stringify({ action: data.action, session_id: data.session_id }),
      })
      var body = await response.json().catch(function () { return {} })
      result = response.ok && body.code === 0
        ? { ok: true, result: body.data }
        : { ok: false, status: response.status, message: body.msg || (response.status === 403 ? '请刷新 fancyqube 页面后重试' : '请重新登录 fancyqube 后重试') }
    } catch (_) {
      result = { ok: false, status: 503, message: '暂时无法连接 fancyqube，请稍后重试' }
    } finally {
      clearTimeout(abortTimeout)
      authRequestPending = false
    }
    destination.postMessage(Object.assign({ protocol: protocol, type: 'auth-result', request_id: data.request_id }, result), assistantUrl.origin)
  }
  shadow.querySelector('.close').onclick = close
  shadow.querySelector('.expand').onclick = function () {
    var wide = panel.classList.toggle('wide')
    this.title = wide ? '恢复面板宽度' : '展开面板'
    this.setAttribute('aria-label', this.title)
    this.setAttribute('aria-pressed', String(wide))
    this.innerHTML = icon(wide ? 'scale-to-original' : 'full-screen')
  }
  shadow.querySelector('.external').onclick = function () {
    window.open(new URL('/workspace/chat', assistantUrl).href, '_blank', 'noopener,noreferrer')
  }
  shadow.addEventListener('keydown', function (event) { if (event.key === 'Escape') close() })
  document.addEventListener('pointerdown', function (event) {
    if (event.composedPath().indexOf(root) < 0) { activeFrame = null; context = pageContext(); sendContext() }
  }, { passive: true })
  window.addEventListener('message', function (event) {
    if (event.data?.protocol !== protocol) return
    if (frame && event.source === frame.contentWindow && event.origin === assistantUrl.origin) {
      if (event.data.type === 'ready') {
        ready = true
        supportsPrompt = event.data.submitPrompt === true
        clearTimeout(timeout)
        status.hidden = true
        sendVisibility()
        update()
        sendPrompt()
      }
      if (event.data.type === 'auth-request') handleAuthRequest(event.data)
      if (event.data.type === 'submit-prompt-result' && pendingPrompt?.sent && event.data.id === pendingPrompt.message.id) {
        finishPrompt(event.data.ok === true ? '' : (event.data.error || 'AI Hub 未能提交提示词'))
      }
      return
    }
    if (event.origin !== location.origin || event.data.type !== 'business-page') return
    var childFrame = Array.from(document.querySelectorAll('iframe')).find(function (element) { return element.contentWindow === event.source })
    if (!childFrame) return
    try {
      if (new URL(event.data.context.url).origin !== location.origin) return
      activeFrame = childFrame
      context = event.data.context
      sendContext()
    } catch (_) { /* Ignore malformed business-page messages. */ }
  })
  window.addEventListener('hashchange', update)
  window.addEventListener('popstate', update)
  window.__aihubAssistant = { open: open, close: close, update: update, submit: submit }
})()
