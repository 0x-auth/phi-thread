/**
 * phi-thread search engine — browser port
 *
 * Thread Math: every answer has a permanent coordinate.
 *   SO:     stackoverflow.com/a/{answer_id}
 *   Reddit: reddit.com/.../comments/{post}/{comment}
 *   HN:     news.ycombinator.com/item?id={comment_id}
 *   GitHub: github.com/.../issues/{n}
 *
 * Three layers:
 *   1. Cache (chrome.storage.local, 24hr TTL)
 *   2. Keyword index (persistent, grows forever)
 *   3. Live search (5 platform APIs)
 */

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// KEYWORDS
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

const STOPWORDS = new Set([
  'the','a','an','is','are','was','were','be','been',
  'have','has','had','do','does','did','will','would',
  'could','should','may','might','can','to','of','in',
  'for','on','with','at','by','from','it','this','that',
  'and','or','but','not','no','so','if','how','what',
  'when','where','who','which','why','i','you','we',
  'they','he','she','my','your','our','their','keep',
  'keeps','get','getting','got','use','using','error',
]);

function extractKeywords(text) {
  const words = text.toLowerCase().match(/\w+/g) || [];
  return new Set(words.filter(w => !STOPWORDS.has(w) && w.length > 2));
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// CACHE (chrome.storage.local)
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function cacheKey(question) {
  const normalized = question.toLowerCase().trim().replace(/\s+/g, ' ');
  let hash = 0;
  for (let i = 0; i < normalized.length; i++) {
    hash = ((hash << 5) - hash + normalized.charCodeAt(i)) | 0;
  }
  return 'cache_' + Math.abs(hash).toString(16).padStart(8, '0');
}

async function getCached(question) {
  const key = cacheKey(question);
  try {
    const data = await chrome.storage.local.get(key);
    if (data[key] && (Date.now() / 1000 - data[key].cached_at) < 86400) {
      return data[key].answers;
    }
  } catch (e) {}
  return null;
}

async function setCache(question, answers) {
  const key = cacheKey(question);
  await chrome.storage.local.set({
    [key]: { question, cached_at: Date.now() / 1000, answers }
  });
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// KEYWORD INDEX
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async function loadIndex() {
  try {
    const data = await chrome.storage.local.get('phi_index');
    return data.phi_index || {};
  } catch (e) { return {}; }
}

async function saveIndex(index) {
  await chrome.storage.local.set({ phi_index: index });
}

function indexAnswer(index, answer) {
  const keywords = extractKeywords(`${answer.title} ${answer.preview} ${answer.answer_text || ''}`);
  const entry = {
    url: answer.url,
    title: answer.title,
    platform: answer.platform,
    coordinate: answer.coordinate,
    score: answer.score,
  };
  for (const kw of keywords) {
    if (!index[kw]) index[kw] = [];
    if (!index[kw].some(e => e.url === answer.url)) {
      index[kw].push(entry);
      if (index[kw].length > 20) {
        index[kw].sort((a, b) => b.score - a.score);
        index[kw] = index[kw].slice(0, 20);
      }
    }
  }
}

function searchIndex(index, question, maxResults) {
  const keywords = extractKeywords(question);
  if (keywords.size === 0) return [];

  const urlScores = {};
  for (const kw of keywords) {
    for (const entry of (index[kw] || [])) {
      if (!urlScores[entry.url]) urlScores[entry.url] = { score: 0, entry };
      urlScores[entry.url].score += entry.score;
    }
  }

  return Object.values(urlScores)
    .map(({ score, entry }) => ({
      platform: entry.platform,
      title: entry.title,
      url: entry.url,
      score,
      thread_id: (entry.coordinate || '').split(':').pop().split('/')[0],
      answer_id: '',
      timestamp: 0,
      preview: `[indexed] ${entry.coordinate}`,
      answer_text: '',
      is_accepted: false,
      depth: 0,
      coordinate: entry.coordinate || '',
    }))
    .sort((a, b) => b.score - a.score)
    .slice(0, maxResults);
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// HELPERS
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

function stripHtml(text) {
  return text.replace(/<[^>]+>/g, ' ').replace(/&amp;/g, '&').replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>').replace(/&quot;/g, '"').replace(/&#x27;/g, "'")
    .replace(/&nbsp;/g, ' ').replace(/\s+/g, ' ').trim();
}

function makeCoordinate(platform, threadId, answerId) {
  if (answerId && answerId !== threadId) return `${platform}:${threadId}/${answerId}`;
  return `${platform}:${threadId}`;
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// PLATFORM SEARCHERS
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async function searchStackOverflow(query, limit) {
  try {
    const url = `https://api.stackexchange.com/2.3/search/advanced?order=desc&sort=relevance&q=${query}&site=stackoverflow&filter=default&pagesize=${limit}`;
    const resp = await fetch(url);
    const data = await resp.json();

    const questionIds = [];
    const questionsMap = {};

    for (const item of (data.items || []).slice(0, limit)) {
      if (item.is_answered) {
        questionIds.push(item.question_id);
        questionsMap[item.question_id] = item;
      }
    }

    // Deep-link: fetch accepted answers
    const answerMap = questionIds.length > 0 ? await fetchSOAnswers(questionIds.slice(0, 10)) : {};

    const answers = [];
    for (const [qid, item] of Object.entries(questionsMap)) {
      const acceptedId = item.accepted_answer_id;
      const answerData = answerMap[qid];

      let deepUrl, answerText, depth;
      if (acceptedId) {
        deepUrl = `https://stackoverflow.com/a/${acceptedId}`;
        answerText = answerData ? stripHtml(answerData.body || '').slice(0, 200) : '';
        depth = 1;
      } else {
        deepUrl = item.link || '';
        answerText = '';
        depth = 0;
      }

      let soScore = 5.0 + (item.answer_count || 0) * 1.5 + (item.view_count || 0) / 5000 + (item.score || 0) * 0.5;
      if (acceptedId) soScore *= 1.3;

      answers.push({
        platform: 'stackoverflow',
        title: stripHtml(item.title || ''),
        url: deepUrl,
        score: soScore,
        thread_id: String(qid),
        answer_id: String(acceptedId || qid),
        timestamp: item.creation_date || 0,
        preview: (item.tags || []).slice(0, 5).join(', '),
        answer_text: answerText,
        is_accepted: !!acceptedId,
        depth,
        coordinate: makeCoordinate('stackoverflow', String(qid), String(acceptedId || qid)),
      });
    }
    return answers;
  } catch (e) { return []; }
}

async function fetchSOAnswers(questionIds) {
  try {
    const idsStr = questionIds.join(';');
    const url = `https://api.stackexchange.com/2.3/questions/${idsStr}/answers?order=desc&sort=votes&site=stackoverflow&filter=withbody&pagesize=30`;
    const resp = await fetch(url);
    const data = await resp.json();

    const result = {};
    for (const item of (data.items || [])) {
      const qid = item.question_id;
      if (qid && (item.is_accepted || !result[qid])) {
        result[qid] = item;
      }
    }
    return result;
  } catch (e) { return {}; }
}

async function searchReddit(query, limit) {
  try {
    const url = `https://www.reddit.com/search.json?q=${query}&sort=relevance&limit=${limit}&type=link`;
    const resp = await fetch(url, { headers: { 'User-Agent': 'phi-thread/0.2' } });
    const data = await resp.json();

    const posts = (data.data?.children || [])
      .slice(0, limit)
      .map(c => c.data)
      .filter(p => (p.num_comments || 0) > 2);

    const answers = [];
    for (const post of posts.slice(0, 5)) {
      const rScore = (post.score || 0) * 0.01 + (post.num_comments || 0) * 0.1;
      const topComment = await fetchRedditTopComment(post.permalink);

      if (topComment) {
        answers.push({
          platform: 'reddit',
          title: post.title || '',
          url: `https://reddit.com${post.permalink}${topComment.id}`,
          score: rScore,
          thread_id: post.id || '',
          answer_id: topComment.id,
          timestamp: post.created_utc || 0,
          preview: `r/${post.subreddit || ''} | top comment`,
          answer_text: topComment.body.slice(0, 200),
          is_accepted: false,
          depth: 1,
          coordinate: makeCoordinate('reddit', post.id || '', topComment.id),
        });
      } else {
        answers.push({
          platform: 'reddit',
          title: post.title || '',
          url: `https://reddit.com${post.permalink}`,
          score: rScore,
          thread_id: post.id || '',
          answer_id: post.id || '',
          timestamp: post.created_utc || 0,
          preview: `r/${post.subreddit || ''} | ${post.num_comments || 0} comments`,
          answer_text: '',
          is_accepted: false,
          depth: 0,
          coordinate: makeCoordinate('reddit', post.id || '', post.id || ''),
        });
      }
    }
    return answers;
  } catch (e) { return []; }
}

async function fetchRedditTopComment(permalink) {
  if (!permalink) return null;
  try {
    const url = `https://www.reddit.com${permalink}.json?limit=1&sort=top`;
    const resp = await fetch(url, { headers: { 'User-Agent': 'phi-thread/0.2' } });
    const data = await resp.json();

    if (data.length >= 2) {
      for (const c of (data[1].data?.children || [])) {
        if (c.kind === 't1' && c.data?.body && (c.data.score || 0) > 1) {
          return { id: c.data.id, body: c.data.body, score: c.data.score };
        }
      }
    }
  } catch (e) {}
  return null;
}

async function searchHN(query, limit) {
  try {
    const url = `https://hn.algolia.com/api/v1/search?query=${query}&hitsPerPage=${limit}`;
    const resp = await fetch(url);
    const data = await resp.json();

    return (data.hits || []).slice(0, limit).map(hit => {
      const hnScore = (hit.points || 0) * 0.05 + (hit.num_comments || 0) * 0.1;
      const storyId = hit.story_id || hit.objectID || '';
      const objectId = hit.objectID || '';
      const isComment = hit.story_id && (hit._tags || []).includes('comment');

      let hnUrl, depth, title, previewText;
      if (isComment) {
        hnUrl = `https://news.ycombinator.com/item?id=${objectId}`;
        depth = 1;
        title = hit.story_title || hit.title || '';
        previewText = hit.comment_text ? stripHtml(hit.comment_text).slice(0, 150) : '';
      } else {
        hnUrl = hit.url || `https://news.ycombinator.com/item?id=${objectId}`;
        depth = 0;
        title = hit.title || '';
        previewText = `${hit.points || 0} pts | ${hit.num_comments || 0} comments`;
      }

      return {
        platform: 'hn',
        title,
        url: hnUrl,
        score: hnScore,
        thread_id: String(storyId),
        answer_id: String(objectId),
        timestamp: hit.created_at_i || 0,
        preview: previewText,
        answer_text: '',
        is_accepted: false,
        depth,
        coordinate: makeCoordinate('hn', String(storyId), String(objectId)),
      };
    });
  } catch (e) { return []; }
}

async function searchGitHub(query, limit) {
  try {
    const url = `https://api.github.com/search/issues?q=${query}&sort=relevance&per_page=${limit}`;
    const resp = await fetch(url, {
      headers: { 'Accept': 'application/vnd.github.v3+json', 'User-Agent': 'phi-thread/0.2' }
    });
    const data = await resp.json();

    return (data.items || []).slice(0, limit).map(item => {
      const ghScore = (item.comments || 0) * 0.2 + (item.reactions?.total_count || 0) * 0.1;
      const repoUrl = item.repository_url || '';
      const repoName = repoUrl.split('/').slice(-2).join('/');

      return {
        platform: 'github',
        title: item.title || '',
        url: item.html_url || '',
        score: ghScore,
        thread_id: String(item.number || ''),
        answer_id: String(item.number || ''),
        timestamp: Date.now() / 1000,
        preview: repoName,
        answer_text: '',
        is_accepted: false,
        depth: 0,
        coordinate: makeCoordinate('github', String(item.number || ''), String(item.number || '')),
      };
    });
  } catch (e) { return []; }
}

async function searchDDG(query, limit) {
  try {
    const url = `https://html.duckduckgo.com/html/?q=${query}`;
    const resp = await fetch(url, { headers: { 'User-Agent': 'phi-thread/0.2' } });
    const html = await resp.text();

    const resultPattern = /<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>([\s\S]*?)<\/a>/g;
    const snippetPattern = /<a[^>]+class="result__snippet"[^>]*>([\s\S]*?)<\/a>/g;

    const results = [];
    let m;
    while ((m = resultPattern.exec(html)) !== null) results.push({ url: m[1], title: m[2] });

    const snippets = [];
    while ((m = snippetPattern.exec(html)) !== null) snippets.push(m[1]);

    const seen = new Set();
    const skipDomains = ['stackoverflow.com', 'reddit.com', 'news.ycombinator.com', 'github.com'];
    const answers = [];

    for (let i = 0; i < Math.min(results.length, limit); i++) {
      let resultUrl = results[i].url;
      const uddgMatch = resultUrl.match(/uddg=([^&]+)/);
      if (uddgMatch) resultUrl = decodeURIComponent(uddgMatch[1]);

      const resultTitle = stripHtml(results[i].title);
      const snippet = i < snippets.length ? stripHtml(snippets[i]) : '';

      if (seen.has(resultUrl)) continue;
      if (skipDomains.some(d => resultUrl.includes(d))) continue;
      seen.add(resultUrl);

      let platform = 'web';
      if (resultUrl.includes('twitter.com') || resultUrl.includes('x.com')) platform = 'twitter';
      else if (resultUrl.includes('dev.to')) platform = 'devto';
      else if (resultUrl.includes('medium.com')) platform = 'medium';
      else if (resultUrl.includes('serverfault.com')) platform = 'serverfault';
      else if (resultUrl.includes('superuser.com')) platform = 'superuser';

      const hash = Math.abs(resultUrl.split('').reduce((h, c) => ((h << 5) - h + c.charCodeAt(0)) | 0, 0)).toString(16).slice(0, 12);

      answers.push({
        platform,
        title: resultTitle,
        url: resultUrl,
        score: 2.0,
        thread_id: hash,
        answer_id: hash,
        timestamp: Date.now() / 1000,
        preview: snippet.slice(0, 100) || `via web | ${platform}`,
        answer_text: '',
        is_accepted: false,
        depth: 0,
        coordinate: makeCoordinate(platform, hash, hash),
      });
    }
    return answers;
  } catch (e) { return []; }
}

// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
// MAIN SEARCH ORCHESTRATOR
// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

async function phiSearch(question, platforms = null, maxResults = 8) {
  // Layer 1: Cache
  const cached = await getCached(question);
  if (cached) return cached.slice(0, maxResults);

  if (!platforms) platforms = ['stackoverflow', 'reddit', 'hn', 'github', 'google'];

  // Layer 2: Keyword index
  const index = await loadIndex();
  const indexed = searchIndex(index, question, maxResults);

  // Layer 3: Live search — PARALLEL (faster than CLI!)
  const query = encodeURIComponent(question);
  const searches = [];

  if (platforms.includes('stackoverflow')) searches.push(searchStackOverflow(query, maxResults));
  if (platforms.includes('reddit')) searches.push(searchReddit(query, maxResults));
  if (platforms.includes('hn')) searches.push(searchHN(query, maxResults));
  if (platforms.includes('github')) searches.push(searchGitHub(query, maxResults));
  if (platforms.includes('google')) searches.push(searchDDG(query, maxResults));

  const liveResults = (await Promise.all(searches)).flat();

  // Combine (dedup by URL)
  const seen = new Set();
  const all = [];
  for (const a of [...liveResults, ...indexed]) {
    if (!seen.has(a.url)) {
      seen.add(a.url);
      all.push(a);
    }
  }

  // Rank: score × title relevance
  const queryWords = extractKeywords(question);
  for (const answer of all) {
    const titleWords = extractKeywords(answer.title);
    let overlap = 0.5;
    if (queryWords.size > 0) {
      let matches = 0;
      for (const w of queryWords) { if (titleWords.has(w)) matches++; }
      overlap = matches / queryWords.size;
    }
    answer.score *= Math.max(0.1, overlap);
  }

  all.sort((a, b) => b.score - a.score);
  const final = all.slice(0, maxResults);

  // Index all answers
  for (const a of final) indexAnswer(index, a);
  await saveIndex(index);

  // Cache
  if (final.length > 0) await setCache(question, final);

  return final;
}

// Export for use by background.js
if (typeof globalThis !== 'undefined') {
  globalThis.phiSearch = phiSearch;
  globalThis.extractKeywords = extractKeywords;
}
