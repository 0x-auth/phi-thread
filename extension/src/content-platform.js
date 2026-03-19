/**
 * Content script: injected on SO, Reddit, HN question pages.
 * Shows "related answers from OTHER platforms" in a floating panel.
 */

(function () {
  if (document.getElementById('phi-thread-related')) return;

  // Extract page title as query
  let query = '';
  const hostname = window.location.hostname;

  if (hostname.includes('stackoverflow.com')) {
    const titleEl = document.getElementById('question-header');
    query = titleEl ? titleEl.textContent.trim() : document.title.replace(/ - Stack Overflow$/, '');
  } else if (hostname.includes('reddit.com')) {
    const titleEl = document.querySelector('h1');
    query = titleEl ? titleEl.textContent.trim() : document.title;
  } else if (hostname.includes('ycombinator.com')) {
    const titleEl = document.querySelector('.titleline a');
    query = titleEl ? titleEl.textContent.trim() : document.title;
  }

  if (!query || query.length < 5) return;

  // Exclude current platform from search
  let excludePlatform = '';
  if (hostname.includes('stackoverflow')) excludePlatform = 'stackoverflow';
  else if (hostname.includes('reddit')) excludePlatform = 'reddit';
  else if (hostname.includes('ycombinator')) excludePlatform = 'hn';

  const platforms = ['stackoverflow', 'reddit', 'hn', 'github', 'google'].filter(p => p !== excludePlatform);

  // Build floating panel (bottom-right)
  const host = document.createElement('div');
  host.id = 'phi-thread-related';
  host.style.cssText = `
    position: fixed; bottom: 16px; right: 16px; z-index: 999999;
    width: 320px;
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
      max-height: 400px;
      display: flex;
      flex-direction: column;
    }
    .panel-header {
      padding: 10px 12px;
      border-bottom: 1px solid #1a1a2a;
      display: flex;
      align-items: center;
      justify-content: space-between;
      flex-shrink: 0;
    }
    .panel-header .logo {
      font-size: 0.82rem;
      font-weight: 700;
      background: linear-gradient(135deg, #00d4ff, #7b2ffc);
      -webkit-background-clip: text;
      -webkit-text-fill-color: transparent;
    }
    .panel-header .subtitle {
      font-size: 0.62rem;
      color: #555;
      margin-left: 6px;
    }
    .panel-header .close {
      background: none; border: none; color: #555; font-size: 1rem;
      cursor: pointer; padding: 2px 6px; border-radius: 4px;
    }
    .panel-header .close:hover { color: #fff; background: #252540; }
    .panel-status {
      padding: 5px 12px;
      font-size: 0.65rem;
      color: #555;
      flex-shrink: 0;
    }
    .panel-status.loading { color: #7b2ffc; }
    .panel-results {
      overflow-y: auto;
      padding: 2px 4px 8px;
      flex-grow: 1;
    }
    .result {
      padding: 8px 8px;
      border-radius: 6px;
      cursor: pointer;
      transition: background 0.15s;
    }
    .result:hover { background: rgba(123,47,252,0.08); }
    .r-title {
      font-size: 0.78rem;
      font-weight: 500;
      color: #e0e0e0;
      line-height: 1.3;
    }
    .r-meta {
      margin-top: 2px;
      font-size: 0.65rem;
      color: #666;
      display: flex;
      align-items: center;
      gap: 4px;
    }
    .r-platform {
      font-weight: 600; font-size: 0.6rem;
      padding: 1px 4px; border-radius: 3px;
    }
    .plat-stackoverflow { background: rgba(244,128,36,0.15); color: #f48024; }
    .plat-reddit { background: rgba(255,69,0,0.15); color: #ff4500; }
    .plat-hn { background: rgba(255,102,0,0.15); color: #ff6600; }
    .plat-github { background: rgba(200,200,200,0.12); color: #ccc; }
    .plat-twitter { background: rgba(29,161,242,0.15); color: #1da1f2; }
    .plat-medium { background: rgba(34,197,94,0.15); color: #22c55e; }
    .plat-devto { background: rgba(153,102,255,0.15); color: #9966ff; }
    .plat-web { background: rgba(150,150,150,0.1); color: #888; }
    .r-url {
      margin-top: 2px; font-size: 0.58rem;
      color: #00a0cc; white-space: nowrap;
      overflow: hidden; text-overflow: ellipsis;
    }
    .depth-tag {
      font-size: 0.55rem; padding: 1px 4px;
      border-radius: 6px; font-weight: 600; margin-left: 4px;
    }
    .depth-accepted { background: rgba(34,197,94,0.15); color: #22c55e; }
    .depth-top { background: rgba(245,158,11,0.15); color: #f59e0b; }
    .fab {
      background: linear-gradient(135deg, #7b2ffc, #00d4ff);
      border: none; border-radius: 50%; width: 44px; height: 44px;
      color: #fff; font-size: 1.2rem; cursor: pointer;
      box-shadow: 0 4px 16px rgba(123,47,252,0.4);
      display: none; margin-left: auto;
    }
    .fab:hover { transform: scale(1.1); }
  `;

  const LABELS = {
    stackoverflow: 'SO', reddit: 'Reddit', hn: 'HN', github: 'GitHub',
    twitter: 'Twitter', medium: 'Medium', devto: 'Dev.to', web: 'Web',
  };

  const style = document.createElement('style');
  style.textContent = STYLES;
  shadow.appendChild(style);

  const panel = document.createElement('div');
  panel.className = 'panel';
  panel.innerHTML = `
    <div class="panel-header">
      <span><span class="logo">phi-thread</span><span class="subtitle">answers from other platforms</span></span>
      <button class="close" title="Close">&times;</button>
    </div>
    <div class="panel-status loading">Searching...</div>
    <div class="panel-results"></div>
  `;
  shadow.appendChild(panel);

  // FAB to reopen
  const fab = document.createElement('button');
  fab.className = 'fab';
  fab.textContent = '\u03C6';
  fab.title = 'phi-thread';
  shadow.appendChild(fab);

  panel.querySelector('.close').addEventListener('click', () => {
    panel.style.display = 'none';
    fab.style.display = 'block';
  });
  fab.addEventListener('click', () => {
    panel.style.display = 'flex';
    fab.style.display = 'none';
  });

  // Search other platforms
  const statusEl = panel.querySelector('.panel-status');
  const resultsEl = panel.querySelector('.panel-results');

  chrome.runtime.sendMessage(
    { type: 'search', query, platforms, maxResults: 5 },
    (response) => {
      if (!response || !response.ok) {
        statusEl.textContent = 'Could not search.';
        statusEl.className = 'panel-status';
        return;
      }

      const results = response.results || [];
      statusEl.textContent = `${results.length} related answers`;
      statusEl.className = 'panel-status';

      if (results.length === 0) {
        resultsEl.innerHTML = '<div style="text-align:center;padding:16px;color:#444;font-size:0.75rem;">No related answers found.</div>';
        return;
      }

      resultsEl.innerHTML = results.map(r => {
        let depthTag = '';
        if (r.is_accepted) depthTag = '<span class="depth-tag depth-accepted">accepted</span>';
        else if (r.depth === 1) depthTag = '<span class="depth-tag depth-top">top answer</span>';

        return `
          <div class="result" data-url="${r.url}">
            <div class="r-title">${r.title}${depthTag}</div>
            <div class="r-meta">
              <span class="r-platform plat-${r.platform}">${LABELS[r.platform] || r.platform}</span>
              <span>${r.preview}</span>
            </div>
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
