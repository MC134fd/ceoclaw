/* ============================================================
   CEOClaw Studio — main.js
   Handles: nav scroll, FAQ accordion, intersection observer
   animations, chat simulation, panel switching, viewport
   toggle, sidebar collapse, toast, preview tabs
   ============================================================ */

'use strict';

// ── Utility ─────────────────────────────────────────────────

const $ = (sel, ctx = document) => ctx.querySelector(sel);
const $$ = (sel, ctx = document) => [...ctx.querySelectorAll(sel)];

function showToast(text, icon = '✓', duration = 3200) {
  const toast = $('#toast');
  if (!toast) return;
  $('#toast-text').textContent = text;
  $('#toast-icon').textContent = icon;
  toast.classList.add('show');
  clearTimeout(toast._timer);
  toast._timer = setTimeout(() => toast.classList.remove('show'), duration);
}

// ── Landing: Sticky nav on scroll ───────────────────────────

(function initNav() {
  const nav = $('#main-nav');
  if (!nav) return;
  const onScroll = () => {
    nav.classList.toggle('scrolled', window.scrollY > 20);
  };
  window.addEventListener('scroll', onScroll, { passive: true });
  onScroll();
})();

// ── Landing: FAQ accordion ───────────────────────────────────

(function initFAQ() {
  $$('.faq-item').forEach(item => {
    const btn = item.querySelector('.faq-item__question');
    if (!btn) return;
    btn.addEventListener('click', () => {
      const isOpen = item.classList.contains('open');
      // Close all
      $$('.faq-item').forEach(i => {
        i.classList.remove('open');
        i.querySelector('.faq-item__question')?.setAttribute('aria-expanded', 'false');
      });
      // Open clicked if it was closed
      if (!isOpen) {
        item.classList.add('open');
        btn.setAttribute('aria-expanded', 'true');
      }
    });
    // Keyboard: Enter or Space
    btn.addEventListener('keydown', e => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        btn.click();
      }
    });
  });
})();

// ── Landing: Entrance animations (IntersectionObserver) ──────

(function initAnimations() {
  if (!window.IntersectionObserver) return;
  const els = $$('.animate-in');
  if (!els.length) return;
  const observer = new IntersectionObserver(entries => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        entry.target.classList.add('visible');
        observer.unobserve(entry.target);
      }
    });
  }, { threshold: 0.12 });
  els.forEach(el => observer.observe(el));
})();

// ── App: Sidebar panel switching ────────────────────────────

(function initSidebarNav() {
  const sidebarItems = $$('.sidebar-item[data-panel]');
  if (!sidebarItems.length) return;

  function activatePanel(panelId) {
    // Update sidebar items
    sidebarItems.forEach(item => {
      const isActive = item.dataset.panel === panelId;
      item.classList.toggle('active', isActive);
      item.setAttribute('aria-current', isActive ? 'page' : 'false');
    });
    // Show/hide panels
    $$('.panel-tab-content').forEach(panel => {
      panel.classList.toggle('active', panel.id === `panel-${panelId}`);
    });
  }

  sidebarItems.forEach(item => {
    item.addEventListener('click', () => activatePanel(item.dataset.panel));
    item.addEventListener('keydown', e => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        activatePanel(item.dataset.panel);
      }
    });
  });

  // Deploy button in topbar → switch to deploy panel
  const deployBtnTop = $('#deploy-btn-top');
  if (deployBtnTop) {
    deployBtnTop.addEventListener('click', () => activatePanel('deploy'));
  }
})();

// ── App: Sidebar collapse toggle ─────────────────────────────

(function initSidebarCollapse() {
  const btn = $('#sidebar-collapse-btn');
  const sidebar = $('#app-sidebar');
  if (!btn || !sidebar) return;
  btn.addEventListener('click', () => {
    const collapsed = sidebar.classList.toggle('collapsed');
    btn.setAttribute('aria-label', collapsed ? 'Expand sidebar' : 'Collapse sidebar');
    btn.innerHTML = collapsed
      ? `<svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="M5 2l5 5-5 5"/></svg>`
      : `<svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" stroke-width="1.8" aria-hidden="true"><path d="M9 2L4 7l5 5"/></svg>`;
  });
})();

// ── App: Preview tab switching ────────────────────────────────

(function initPreviewTabs() {
  const tabs = $$('.preview-tab');
  const previewFrame = $('#preview-frame');
  const codeView = $('#code-view');
  if (!tabs.length) return;

  tabs.forEach(tab => {
    tab.addEventListener('click', () => {
      tabs.forEach(t => {
        t.classList.remove('active');
        t.setAttribute('aria-selected', 'false');
      });
      tab.classList.add('active');
      tab.setAttribute('aria-selected', 'true');

      const view = tab.dataset.view;
      if (view === 'preview') {
        if (previewFrame) previewFrame.style.display = '';
        if (codeView) codeView.style.display = 'none';
      } else if (view === 'code') {
        if (previewFrame) previewFrame.style.display = 'none';
        if (codeView) { codeView.style.display = 'flex'; }
      } else if (view === 'split') {
        if (previewFrame) previewFrame.style.display = '';
        if (codeView) codeView.style.display = 'none';
        showToast('Split view requires the desktop app — opening preview only.', 'ℹ️');
      }
    });
  });
})();

// ── App: Viewport toggle ─────────────────────────────────────

(function initViewportToggle() {
  const btns = $$('.viewport-btn');
  const content = $('#preview-content');
  if (!btns.length) return;

  btns.forEach(btn => {
    btn.addEventListener('click', () => {
      btns.forEach(b => b.classList.remove('active'));
      btn.classList.add('active');
      const vp = btn.dataset.vp;
      if (!content) return;
      if (vp === 'mobile') {
        content.style.maxWidth = '390px';
        content.style.margin = '0 auto';
        content.style.borderLeft = '1px solid var(--border)';
        content.style.borderRight = '1px solid var(--border)';
      } else if (vp === 'tablet') {
        content.style.maxWidth = '768px';
        content.style.margin = '0 auto';
        content.style.borderLeft = '1px solid var(--border)';
        content.style.borderRight = '1px solid var(--border)';
      } else {
        content.style.maxWidth = '';
        content.style.margin = '';
        content.style.borderLeft = '';
        content.style.borderRight = '';
      }
    });
  });
})();

// ── App: Chat generation simulation ──────────────────────────

(function initChatGeneration() {
  const bar = $('#gen-bar');
  const pct = $('#gen-pct');
  const label = $('#gen-label');
  const steps = [
    $('#step-1'), $('#step-2'), $('#step-3'), $('#step-4'), $('#step-5')
  ];
  const loading = $('#preview-loading');
  const loadingText = $('#preview-loading-text');
  const previewContent = $('#preview-content');
  const followupMsg = $('#followup-msg');
  const followupReply = $('#followup-reply');

  if (!bar) return;

  const stepLabels = [
    '● Building layout scaffolding…',
    '● Generating component styles…',
    '● Wiring responsive breakpoints…',
    '● Running accessibility audit…',
    '● Finalizing design tokens…',
  ];

  const stepProgress = [18, 38, 60, 80, 96];
  let stepIndex = 0;
  let progress = 0;

  const stepCompletedAt = [10, 30, 55, 75, 92];

  const tick = setInterval(() => {
    progress = Math.min(progress + (Math.random() * 4 + 1), 100);
    if (bar) {
      bar.style.width = progress + '%';
      bar.setAttribute('aria-valuenow', Math.round(progress));
    }
    if (pct) pct.textContent = Math.round(progress) + '%';

    // Update steps
    stepCompletedAt.forEach((threshold, i) => {
      if (progress >= threshold && steps[i]) {
        steps[i].className = 'gen-step done';
        steps[i].querySelector('.gen-step__icon').textContent = '✓';
      }
    });

    // Update label
    const labelIdx = stepProgress.findIndex(s => progress < s);
    if (labelIdx >= 0 && label) {
      label.textContent = stepLabels[labelIdx];
    }

    if (progress >= 100) {
      clearInterval(tick);
      if (label) label.textContent = '✓ Generation complete';
      if (pct) pct.textContent = '100%';

      // Show preview after short delay
      setTimeout(() => {
        if (loading) loading.style.display = 'none';
        if (previewContent) previewContent.style.display = '';

        // Show follow-up after a moment
        setTimeout(() => {
          if (followupMsg) followupMsg.style.display = '';
          if (followupReply) followupReply.style.display = '';
          const msgs = $('#chat-messages');
          if (msgs) msgs.scrollTop = msgs.scrollHeight;
        }, 1400);
      }, 400);
    }
  }, 140);
})();

// ── App: Chat send ────────────────────────────────────────────

(function initChatSend() {
  const input = $('#chat-input');
  const sendBtn = $('#chat-send');
  const messagesEl = $('#chat-messages');
  const typingEl = $('#typing-indicator');
  if (!input || !sendBtn || !messagesEl) return;

  // Hint chips → populate input
  $$('.hint-chip').forEach(chip => {
    chip.addEventListener('click', () => {
      input.value = chip.textContent.trim();
      input.focus();
    });
  });

  function sendMessage() {
    const text = input.value.trim();
    if (!text) return;

    // Add user message
    const userMsg = document.createElement('div');
    userMsg.className = 'chat-msg user';
    userMsg.innerHTML = `
      <span class="chat-msg__role">You</span>
      <div class="chat-msg__bubble">${escapeHTML(text)}</div>
    `;
    if (typingEl) messagesEl.insertBefore(userMsg, typingEl);
    else messagesEl.appendChild(userMsg);

    input.value = '';
    messagesEl.scrollTop = messagesEl.scrollHeight;

    // Show typing indicator
    if (typingEl) {
      typingEl.style.display = 'flex';
      messagesEl.scrollTop = messagesEl.scrollHeight;
    }

    // Simulate AI response
    setTimeout(() => {
      if (typingEl) typingEl.style.display = 'none';

      const aiMsg = document.createElement('div');
      aiMsg.className = 'chat-msg ai';
      aiMsg.innerHTML = `
        <span class="chat-msg__role">Studio AI</span>
        <div class="chat-msg__bubble">${getAIResponse(text)}</div>
      `;
      messagesEl.appendChild(aiMsg);
      messagesEl.scrollTop = messagesEl.scrollHeight;
    }, 1600 + Math.random() * 800);
  }

  sendBtn.addEventListener('click', sendMessage);
  input.addEventListener('keydown', e => {
    if (e.key === 'Enter' && (e.metaKey || e.ctrlKey)) {
      e.preventDefault();
      sendMessage();
    }
  });
})();

function escapeHTML(str) {
  return str
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

function getAIResponse(input) {
  const lower = input.toLowerCase();
  if (lower.includes('minimal') || lower.includes('simpler') || lower.includes('clean'))
    return 'Got it — reducing visual density, removing decorative elements, and simplifying the layout. Preview will update shortly.';
  if (lower.includes('dark') || lower.includes('dark mode'))
    return 'Applying a full dark theme — deep background, elevated surfaces, and adjusted contrast for all text and interactive elements.';
  if (lower.includes('color') || lower.includes('palette'))
    return 'Switching the color palette. What direction? E.g., "warmer tones", "purple accent", "earth palette", or paste a hex code.';
  if (lower.includes('mobile') || lower.includes('responsive'))
    return 'Running a responsive pass — tightening breakpoints at 768px and 390px, adjusting grid columns, font sizes, and touch targets.';
  if (lower.includes('pricing'))
    return 'Adding a 3-tier pricing table — Free, Pro, and Enterprise — with feature comparison rows and a CTA button per tier.';
  if (lower.includes('font') || lower.includes('typograph'))
    return 'Updating typography. I\'ll swap the geometric sans for a humanist option and increase the heading weight for more punch.';
  if (lower.includes('add') || lower.includes('section'))
    return `Adding the requested section now. I'll keep the visual language consistent with the rest of the design.`;
  return `Understood. Applying your changes to the current design — the preview will update in a moment. Let me know if you'd like any further refinements.`;
}

// ── App: Export button ────────────────────────────────────────

(function initExportBtn() {
  const btn = $('#export-btn');
  if (!btn) return;
  btn.addEventListener('click', () => {
    showToast('Preparing export… files ready in your Downloads folder.', '📦');
  });
})();

// ── App: Deploy action ────────────────────────────────────────

(function initDeployAction() {
  const btn = $('#deploy-action-btn');
  if (!btn) return;
  btn.addEventListener('click', () => {
    btn.disabled = true;
    btn.innerHTML = `
      <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" stroke-width="2" style="animation:spin 0.8s linear infinite" aria-hidden="true">
        <circle cx="7" cy="7" r="5" stroke-dasharray="20" stroke-dashoffset="10" opacity="0.4"/>
        <path d="M7 2a5 5 0 015 5" stroke-linecap="round"/>
      </svg>
      Deploying…
    `;
    setTimeout(() => {
      btn.disabled = false;
      btn.innerHTML = `
        <svg width="14" height="14" viewBox="0 0 14 14" fill="none" stroke="currentColor" stroke-width="2" aria-hidden="true"><path d="M2 7l3 3 6-6" stroke-linecap="round" stroke-linejoin="round"/></svg>
        Deployed ✓
      `;
      btn.style.background = 'var(--surface)';
      btn.style.color = 'var(--primary)';
      btn.style.border = '1.5px solid rgba(0,229,160,0.3)';
      showToast('🚀 Deployed to Vercel — your site is live.', '🚀', 5000);
    }, 2400);
  });
})();

// ── App: Toast close ─────────────────────────────────────────

(function initToastClose() {
  const btn = $('#toast-close');
  const toast = $('#toast');
  if (!btn || !toast) return;
  btn.addEventListener('click', () => toast.classList.remove('show'));
})();

// ── App: Deploy options selection ────────────────────────────

(function initDeployOptions() {
  $$('.deploy-option').forEach(opt => {
    opt.addEventListener('click', () => {
      $$('.deploy-option').forEach(o => {
        o.classList.remove('selected');
        o.setAttribute('aria-selected', 'false');
      });
      opt.classList.add('selected');
      opt.setAttribute('aria-selected', 'true');
    });
    opt.addEventListener('keydown', e => {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        opt.click();
      }
    });
  });
})();

// ── Mobile nav toggle ────────────────────────────────────────

(function initMobileNav() {
  const toggle = $('#mobile-nav-toggle');
  const links = $('.nav__links');
  if (!toggle || !links) return;

  toggle.addEventListener('click', () => {
    const expanded = toggle.getAttribute('aria-expanded') === 'true';
    toggle.setAttribute('aria-expanded', String(!expanded));

    if (!expanded) {
      links.style.display = 'flex';
      links.style.flexDirection = 'column';
      links.style.position = 'absolute';
      links.style.top = 'var(--nav-h)';
      links.style.left = '0';
      links.style.right = '0';
      links.style.background = 'rgba(8,11,16,0.97)';
      links.style.borderBottom = '1px solid var(--border)';
      links.style.padding = 'var(--sp-4)';
      links.style.backdropFilter = 'blur(12px)';
      links.style.zIndex = '99';
    } else {
      links.style.display = '';
    }
  });
})();
