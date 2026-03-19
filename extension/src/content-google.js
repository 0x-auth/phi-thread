/**
 * Content script: injected on Google/DDG/Bing search pages.
 * Extracts search query, asks background for phi-thread results,
 * renders a sidebar panel on the right.
 */

(function () {
  if (document.getElementById('phi-thread-sidebar')) return;

  // Extract query from URL
  const params = new URLSearchParams(window.location.search);
  const query = params.get('q');
  if (!query || query.length < 3) return;

  // Build sidebar container (shadow DOM to isolate styles)
  const host = document.createElement('div');
  host.id = 'phi-thread-sidebar';
  host.style.cssText = `
    position: fixed; top: 80px; right: 16px; z-index: 999999;
    width: 340px; max-height: calc(100vh - 100px);
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  `;
  document.body.appendChild(host);
  const shadow = host.attachShadow({ mode: 'closed' });

  const STYLES = `
    :host { all: initial; }
    * { margin: 0; padding: 0; box-sizing: border-box; }
    .panel {
      background: #0d0d14;
      border: 1px solid #252540;
      border-radius: 12px;
      overflow: hidden;
      box-shadow: 0 8px 32px rgba(0,0,0,0.5);
      max-height: calc(100vh - 100px);
      display: flex;
      flex-direction: column;
    }
    .panel-header {
      padding: 12px 14px;
      border-bottom: 1px solid #1a1a2a;
      display: flex;
      align-items: center;
      justify-content: space-between;
      flex-shrink: 0;
    }
    .panel-header .logo {
      font-size: 0.9rem;
      font-weight: 700;
      background: linear-gradient(135deg, #00d4ff, #7b2ffc);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
    }
    .panel-header .close {
      background: none; border: none; color: #555; font-size: 1.1rem;
      cursor: pointer; padding: 2px 6px; border-radius: 4px;
    }
    .panel-header .close:hover { color: #fff; background: #252540; }
    .panel-status {
      padding: 6px 14px;
      font-size: 0.7rem;
      color: #555;
      flex-shrink: 0;
    }
    .panel-status.loading { color: #7b2ffc; }
    .panel-results {
      overflow-y: auto;
      padding: 4px 6px 10px;
      flex-grow: 1;
    }
    .result {
      padding: 10px 10px;
      border-radius: 6px;
      cursor: pointer;
      transition: background 0.15s;
    }
    .result:hover { background: rgba(123,47,252,0.08); }
    .r-title {
      font-size: 0.82rem;
      font-weight: 500;
      color: #e0e0e0;
      line-height: 1.3;
    }
    .r-meta {
      margin-top: 3px;
      font-size: 0.68rem;
      color: #666;
      display: flex;
      align-items: center;
      gap: 5px;
    }
    .r-platform {
      font-weight: 600;
      font-size: 0.62rem;
      padding: 1px 5px;
      border-radius: 3px;
    }
    .plat-stackoverflow { background: rgba(244,128,36,0.15); color: #f48024; }
    .plat-reddit { background: rgba(255,69,0,0.15); color: #ff4500; }
    .plat-hn { background: rgba(255,102,0,0.15); color: #ff6600; }
    .plat-github { background: rgba(200,200,200,0.12); color: #ccc; }
    .plat-twitter { background: rgba(29,161,242,0.15); color: #1da1f2; }
    .plat-medium { background: rgba(34,197,94,0.15); color: #22c55e; }
    .plat-devto { background: rgba(153,102,255,0.15); color: #9966ff; }
    .plat-web { background: rgba(150,150,150,0.1); color: #888; }
    .r-snippet {
      margin-top: 3px;
      font-size: 0.68rem;
      color: #555;
      font-style: italic;
      line-height: 1.3;
      display: -webkit-box;
      -webkit-line-clamp: 2;
      -webkit-box-orient: vertical;
      overflow: hidden;
    }
    .r-url {
      margin-top: 2px;
      font-size: 0.6rem;
      color: #00a0cc;
      white-space: nowrap;
      overflow: hidden;
      text-overflow: ellipsis;
    }
    .depth-tag {
      font-size: 0.58rem;
      padding: 1px 5px;
      border-radius: 8px;
      font-weight: 600;
      margin-left: 4px;
    }
    .depth-accepted { background: rgba(34,197,94,0.15); color: #22c55e; }
    .depth-top { background: rgba(245,158,11,0.15); color: #f59e0b; }
    .collapse-btn {
      background: #0d0d14; border: 1px solid #252540; border-radius: 8px;
      color: #7b2ffc; padding: 6px 12px; cursor: pointer; font-size: 0.75rem;
      font-weight: 600; box-shadow: 0 4px 16px rgba(0,0,0,0.4);
      display: none;
    }
    .collapse-btn:hover { background: #15152a; }
  `;

  const LABELS = {
    stackoverflow: 'SO', reddit: 'Reddit', hn: 'HN', github: 'GitHub',
    twitter: 'Twitter', medium: 'Medium', devto: 'Dev.to', web: 'Web',
  };

  // Build HTML
  const style = document.createElement('style');
  style.textContent = STYLES;
  shadow.appendChild(style);

  const panel = document.createElement('div');
  panel.className = 'panel';
  panel.innerHTML = `
    <div class="panel-header">
      <span class="logo">phi-thread</span>
      <button class="close" title="Close">&times;</button>
    </div>
    <div class="panel-status loading">Searching across platforms...</div>
    <div class="panel-results"></div>
  `;
  shadow.appendChild(panel);

  // Collapse button (shows after closing)
  const collapseBtn = document.createElement('button');
  collapseBtn.className = 'collapse-btn';
  collapseBtn.textContent = 'phi-thread';
  shadow.appendChild(collapseBtn);

  // Close / reopen
  panel.querySelector('.close').addEventListener('click', () => {
    panel.style.display = 'none';
    collapseBtn.style.display = 'block';
  });
  collapseBtn.addEventListener('click', () => {
    panel.style.display = 'flex';
    collapseBtn.style.display = 'none';
  });

  // Search
  const statusEl = panel.querySelector('.panel-status');
  const resultsEl = panel.querySelector('.panel-results');

  chrome.runtime.sendMessage(
    { type: 'search', query, maxResults: 6 },
    (response) => {
      if (!response || !response.ok) {
        statusEl.textContent = 'Could not search. Try the popup.';
        statusEl.className = 'panel-status';
        return;
      }

      const results = response.results || [];
      statusEl.textContent = `${results.length} answers from other platforms`;
      statusEl.className = 'panel-status';

      if (results.length === 0) {
        resultsEl.innerHTML = '<div style="text-align:center;padding:20px;color:#444;font-size:0.8rem;">No results found.</div>';
        return;
      }

      resultsEl.innerHTML = results.map(r => {
        let depthTag = '';
        if (r.is_accepted) depthTag = '<span class="depth-tag depth-accepted">accepted</span>';
        else if (r.depth === 1) depthTag = '<span class="depth-tag depth-top">top answer</span>';

        const snippet = r.answer_text
          ? `<div class="r-snippet">"${r.answer_text.slice(0, 100).replace(/\n/g, ' ')}..."</div>`
          : '';

        return `
          <div class="result" data-url="${r.url}">
            <div class="r-title">${r.title}${depthTag}</div>
            <div class="r-meta">
              <span class="r-platform plat-${r.platform}">${LABELS[r.platform] || r.platform}</span>
              <span>${r.preview}</span>
            </div>
            ${snippet}
            <div class="r-url">${r.url}</div>
          </div>
        `;
      }).join('');

      for (const el of resultsEl.querySelectorAll('.result')) {
        el.addEventListener('click', () => window.open(el.dataset.url, '_blank'));
      }
    }
  );
})();
