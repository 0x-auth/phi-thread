/**
 * Service worker — receives search requests from popup + content scripts,
 * runs search (all API calls happen here to avoid CORS), returns results.
 */

importScripts('search.js');

chrome.runtime.onMessage.addListener((msg, sender, sendResponse) => {
  if (msg.type === 'search') {
    phiSearch(msg.query, msg.platforms || null, msg.maxResults || 8)
      .then(results => sendResponse({ ok: true, results }))
      .catch(err => sendResponse({ ok: false, error: err.message }));
    return true; // keep channel open for async response
  }
});
