const PLATFORM_LABELS = {
  stackoverflow: 'SO', reddit: 'Reddit', hn: 'HN', github: 'GitHub',
  twitter: 'Twitter', medium: 'Medium', devto: 'Dev.to',
  serverfault: 'ServerFault', superuser: 'SuperUser', web: 'Web',
};

const queryInput = document.getElementById('query');
const statusEl = document.getElementById('status');
const resultsEl = document.getElementById('results');

let debounceTimer = null;

queryInput.addEventListener('keydown', e => {
  if (e.key === 'Enter') {
    clearTimeout(debounceTimer);
    doSearch(queryInput.value.trim());
  }
});

queryInput.addEventListener('input', () => {
  clearTimeout(debounceTimer);
  const q = queryInput.value.trim();
  if (q.length >= 3) {
    debounceTimer = setTimeout(() => doSearch(q), 800);
  }
});

async function doSearch(query) {
  if (!query) return;

  statusEl.textContent = 'Searching across platforms...';
  statusEl.className = 'status searching';
  resultsEl.innerHTML = '';

  const start = Date.now();

  chrome.runtime.sendMessage(
    { type: 'search', query, maxResults: 8 },
    (response) => {
      const elapsed = ((Date.now() - start) / 1000).toFixed(1);

      if (!response || !response.ok) {
        statusEl.textContent = 'Search failed. Try again.';
        statusEl.className = 'status';
        return;
      }

      const results = response.results || [];
      const isCached = elapsed < 0.1;
      statusEl.textContent = `${isCached ? 'cached' : elapsed + 's'} | ${results.length} answers`;
      statusEl.className = 'status';

      if (results.length === 0) {
        resultsEl.innerHTML = '<div class="empty">No answers found. Try different keywords.</div>';
        return;
      }

      resultsEl.innerHTML = results.map((r, i) => {
        let depthTag = '';
        if (r.is_accepted) depthTag = '<span class="r-depth-tag depth-accepted">accepted answer</span>';
        else if (r.depth === 1) depthTag = '<span class="r-depth-tag depth-top">top answer</span>';

        const snippet = r.answer_text
          ? `<div class="r-snippet">"${r.answer_text.slice(0, 120).replace(/\n/g, ' ')}..."</div>`
          : '';

        const platClass = `plat-${r.platform}`;
        const label = PLATFORM_LABELS[r.platform] || r.platform;

        return `
          <div class="result" data-url="${r.url}">
            <div class="r-top">
              <span class="r-num">${i + 1}.</span>
              <span class="r-title">${r.title}</span>
              ${depthTag}
            </div>
            <div class="r-meta">
              <span class="r-platform ${platClass}">${label}</span>
              <span>${r.preview}</span>
            </div>
            ${snippet}
            <div class="r-url">${r.url}</div>
          </div>
        `;
      }).join('');

      // Click to open
      for (const el of resultsEl.querySelectorAll('.result')) {
        el.addEventListener('click', () => {
          chrome.tabs.create({ url: el.dataset.url });
        });
      }
    }
  );
}
