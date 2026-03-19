"""
Cross-platform answer search with thread math.

Thread Math: every answer on every platform has a permanent coordinate.
  SO:     stackoverflow.com/a/{answer_id}           ← exact answer, not question
  Reddit: reddit.com/.../comments/{post}/{comment}  ← exact comment with fix
  HN:     news.ycombinator.com/item?id={comment_id} ← exact comment, not story
  GitHub: github.com/.../issues/{n}#issuecomment-{id} ← exact comment

This module:
1. Searches platforms for questions matching your query
2. Follows threads INTO the answers (fetches the answer tree)
3. Links to the EXACT answer coordinate, not just the question page
4. Builds a persistent keyword → answer-coordinate index
"""

import json
import time
import hashlib
import html
import urllib.request
import urllib.parse
import re
import gzip
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional, Tuple


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# THREAD COORDINATE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

@dataclass
class Answer:
    """
    A thread coordinate — an exact answer location on a platform.

    Like Slack's timestamp addressing:
      channel/p{ts}?thread_ts={parent_ts}
    But cross-platform:
      platform/thread_id/answer_id → exact URL
    """
    platform: str
    title: str
    url: str                    # Deep-link to exact answer (not question page)
    score: float = 0.0
    thread_id: str = ""         # Parent thread (question/post)
    answer_id: str = ""         # Specific answer/comment within thread
    timestamp: float = 0.0
    preview: str = ""
    answer_text: str = ""       # Snippet of the actual answer
    is_accepted: bool = False   # Accepted/top answer
    depth: int = 0              # 0=question, 1=answer, 2=comment on answer

    @property
    def hash(self) -> str:
        return hashlib.sha256(f"{self.platform}:{self.url}".encode()).hexdigest()[:12]

    @property
    def coordinate(self) -> str:
        """Human-readable thread coordinate."""
        if self.answer_id and self.answer_id != self.thread_id:
            return f"{self.platform}:{self.thread_id}/{self.answer_id}"
        return f"{self.platform}:{self.thread_id}"


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# KEYWORD INDEX (the self-building KB)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

STOPWORDS = {
    'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been',
    'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would',
    'could', 'should', 'may', 'might', 'can', 'to', 'of', 'in',
    'for', 'on', 'with', 'at', 'by', 'from', 'it', 'this', 'that',
    'and', 'or', 'but', 'not', 'no', 'so', 'if', 'how', 'what',
    'when', 'where', 'who', 'which', 'why', 'i', 'you', 'we',
    'they', 'he', 'she', 'my', 'your', 'our', 'their', 'keep',
    'keeps', 'get', 'getting', 'got', 'use', 'using', 'error',
}


def extract_keywords(text: str) -> set:
    """Extract meaningful keywords from text."""
    words = set(re.findall(r'\w+', text.lower()))
    return {w for w in words if w not in STOPWORDS and len(w) > 2}


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# SEARCH ENGINE
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class ThreadSearch:
    """
    Cross-platform answer search with thread math.

    Two layers:
    1. Cache: exact query → results (24hr TTL)
    2. Index: keywords → answer coordinates (persistent, grows forever)

    First ask: live search → cache + index
    Second ask (same query): from cache
    Similar ask (different words): from keyword index
    """

    CACHE_DIR = Path.home() / ".phi-thread" / "cache"
    INDEX_PATH = Path.home() / ".phi-thread" / "index.json"

    def __init__(self):
        self.CACHE_DIR.mkdir(parents=True, exist_ok=True)
        self.index: Dict[str, List[dict]] = {}
        self._load_index()

    def _load_index(self):
        if self.INDEX_PATH.exists():
            try:
                self.index = json.loads(self.INDEX_PATH.read_text())
            except Exception:
                self.index = {}

    def _save_index(self):
        self.INDEX_PATH.write_text(json.dumps(self.index, indent=2))

    def _index_answer(self, answer: Answer):
        """
        Add answer to persistent keyword index.
        Like adding a row to the Slack auto-responder CSV.
        """
        keywords = extract_keywords(f"{answer.title} {answer.preview} {answer.answer_text}")
        entry = {
            'url': answer.url,
            'title': answer.title,
            'platform': answer.platform,
            'coordinate': answer.coordinate,
            'score': answer.score,
            'indexed_at': time.time(),
        }
        for kw in keywords:
            if kw not in self.index:
                self.index[kw] = []
            # Don't duplicate
            if not any(e['url'] == answer.url for e in self.index[kw]):
                self.index[kw].append(entry)
                # Keep top 20 per keyword
                if len(self.index[kw]) > 20:
                    self.index[kw].sort(key=lambda e: e['score'], reverse=True)
                    self.index[kw] = self.index[kw][:20]

    def _search_index(self, question: str, max_results: int) -> List[Answer]:
        """Search the persistent keyword index."""
        keywords = extract_keywords(question)
        if not keywords:
            return []

        # Score each indexed answer by keyword overlap
        url_scores: Dict[str, Tuple[float, dict]] = {}
        for kw in keywords:
            for entry in self.index.get(kw, []):
                url = entry['url']
                if url not in url_scores:
                    url_scores[url] = (0, entry)
                current_score, _ = url_scores[url]
                url_scores[url] = (current_score + entry['score'], entry)

        # Convert to Answer objects
        results = []
        for url, (score, entry) in url_scores.items():
            results.append(Answer(
                platform=entry['platform'],
                title=entry['title'],
                url=url,
                score=score,
                thread_id=entry.get('coordinate', '').split(':')[-1].split('/')[0],
                preview=f"[indexed] {entry['coordinate']}",
            ))

        results.sort(key=lambda a: a.score, reverse=True)
        return results[:max_results]

    def _cache_key(self, question: str) -> str:
        normalized = re.sub(r'\s+', ' ', question.lower().strip())
        return hashlib.sha256(normalized.encode()).hexdigest()[:16]

    def _get_cached(self, question: str) -> Optional[List[Answer]]:
        key = self._cache_key(question)
        cache_file = self.CACHE_DIR / f"{key}.json"
        if cache_file.exists():
            try:
                data = json.loads(cache_file.read_text())
                if time.time() - data.get('cached_at', 0) < 86400:
                    return [Answer(**a) for a in data['answers']]
            except Exception:
                pass
        return None

    def _set_cache(self, question: str, answers: List[Answer]):
        key = self._cache_key(question)
        cache_file = self.CACHE_DIR / f"{key}.json"
        cache_file.write_text(json.dumps({
            'question': question,
            'cached_at': time.time(),
            'answers': [asdict(a) for a in answers],
        }, indent=2))

    def search(
        self,
        question: str,
        platforms: List[str] = None,
        max_results: int = 10,
    ) -> List[Answer]:
        """
        Search for answers. Three layers:
        1. Exact cache (24hr)
        2. Keyword index (persistent)
        3. Live search (fallback)
        """
        # Layer 1: Exact cache
        cached = self._get_cached(question)
        if cached:
            return cached[:max_results]

        # Layer 2: Keyword index (check before live search)
        indexed = self._search_index(question, max_results)

        # Layer 3: Live search
        if platforms is None:
            platforms = ['stackoverflow', 'reddit', 'hn', 'github', 'google']

        live_answers = []
        query = urllib.parse.quote_plus(question)

        if 'stackoverflow' in platforms:
            live_answers.extend(self._search_stackoverflow(query, max_results))

        if 'reddit' in platforms:
            live_answers.extend(self._search_reddit(query, max_results))

        if 'hn' in platforms:
            live_answers.extend(self._search_hn(query, max_results))

        if 'github' in platforms:
            live_answers.extend(self._search_github(query, max_results))

        if 'google' in platforms:
            live_answers.extend(self._search_google(query, max_results))

        # Combine indexed + live (dedup by URL)
        seen_urls = set()
        all_answers = []
        for a in live_answers + indexed:
            if a.url not in seen_urls:
                seen_urls.add(a.url)
                all_answers.append(a)

        # Re-rank by score × title relevance
        query_words = extract_keywords(question)
        for answer in all_answers:
            title_words = extract_keywords(answer.title)
            if query_words:
                overlap = len(query_words & title_words) / len(query_words)
            else:
                overlap = 0.5
            answer.score *= max(0.1, overlap)

        all_answers.sort(key=lambda a: a.score, reverse=True)
        all_answers = all_answers[:max_results]

        # Index all answers for future queries
        for a in all_answers:
            self._index_answer(a)
        self._save_index()

        # Cache for exact query repeat
        if all_answers:
            self._set_cache(question, all_answers)

        return all_answers

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # STACK OVERFLOW — deep-link to exact accepted answer
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def _search_stackoverflow(self, query: str, limit: int) -> List[Answer]:
        answers = []
        try:
            # Use filter that includes accepted_answer_id
            url = (
                f"https://api.stackexchange.com/2.3/search/advanced"
                f"?order=desc&sort=relevance&q={query}"
                f"&site=stackoverflow&filter=default&pagesize={limit}"
            )
            req = urllib.request.Request(url, headers={'Accept-Encoding': 'identity'})
            with urllib.request.urlopen(req, timeout=10) as resp:
                raw = resp.read()
                try:
                    data = json.loads(gzip.decompress(raw))
                except Exception:
                    data = json.loads(raw)

                question_ids = []
                questions_map = {}

                for item in data.get('items', [])[:limit]:
                    if item.get('is_answered'):
                        qid = item['question_id']
                        question_ids.append(qid)
                        questions_map[qid] = item

                # Fetch accepted answers for these questions
                # This gives us the EXACT answer coordinate
                if question_ids:
                    answer_map = self._fetch_so_answers(question_ids[:10])
                else:
                    answer_map = {}

                for qid, item in questions_map.items():
                    accepted_id = item.get('accepted_answer_id')
                    answer_data = answer_map.get(qid)

                    # Build the deep-link
                    if accepted_id:
                        # Link directly to accepted answer
                        deep_url = f"https://stackoverflow.com/a/{accepted_id}"
                        answer_text = ""
                        if answer_data:
                            answer_text = self._strip_html(
                                answer_data.get('body', '')
                            )[:200]
                        depth = 1  # answer level
                    else:
                        # No accepted answer — link to question
                        deep_url = item.get('link', '')
                        answer_text = ""
                        depth = 0

                    so_score = 5.0 + (
                        item.get('answer_count', 0) * 1.5 +
                        item.get('view_count', 0) / 5000 +
                        item.get('score', 0) * 0.5
                    )
                    # Boost accepted answers
                    if accepted_id:
                        so_score *= 1.3

                    answers.append(Answer(
                        platform='stackoverflow',
                        title=html.unescape(item.get('title', '')),
                        url=deep_url,
                        score=so_score,
                        thread_id=str(qid),
                        answer_id=str(accepted_id) if accepted_id else str(qid),
                        timestamp=item.get('creation_date', 0),
                        preview=', '.join(item.get('tags', [])[:5]),
                        answer_text=answer_text,
                        is_accepted=bool(accepted_id),
                        depth=depth,
                    ))
        except Exception:
            pass
        return answers

    def _fetch_so_answers(self, question_ids: List[int]) -> Dict[int, dict]:
        """
        Fetch accepted answers for SO questions.
        Thread math: we're going one level DEEPER into the thread tree.
        question (depth 0) → accepted answer (depth 1)
        """
        if not question_ids:
            return {}

        try:
            ids_str = ';'.join(str(qid) for qid in question_ids)
            url = (
                f"https://api.stackexchange.com/2.3/questions/{ids_str}/answers"
                f"?order=desc&sort=votes&site=stackoverflow"
                f"&filter=withbody&pagesize=30"
            )
            req = urllib.request.Request(url, headers={'Accept-Encoding': 'identity'})
            with urllib.request.urlopen(req, timeout=10) as resp:
                raw = resp.read()
                try:
                    data = json.loads(gzip.decompress(raw))
                except Exception:
                    data = json.loads(raw)

                # Map question_id → top answer
                result = {}
                for item in data.get('items', []):
                    qid = item.get('question_id')
                    if qid and (item.get('is_accepted') or qid not in result):
                        result[qid] = item

                return result
        except Exception:
            return {}

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # REDDIT — deep-link to top comment
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def _search_reddit(self, query: str, limit: int) -> List[Answer]:
        answers = []
        try:
            url = (
                f"https://www.reddit.com/search.json"
                f"?q={query}&sort=relevance&limit={limit}&type=link"
            )
            req = urllib.request.Request(url, headers={
                'User-Agent': 'phi-thread/0.1'
            })
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())

                posts = []
                for child in data.get('data', {}).get('children', [])[:limit]:
                    post = child.get('data', {})
                    if post.get('num_comments', 0) > 2:
                        posts.append(post)

                # For top posts, fetch the actual top comment
                for post in posts[:5]:  # Limit deep fetches
                    r_score = (
                        post.get('score', 0) * 0.01 +
                        post.get('num_comments', 0) * 0.1
                    )

                    # Try to get top comment (thread depth 1)
                    top_comment = self._fetch_reddit_top_comment(post.get('permalink', ''))

                    if top_comment:
                        # Deep-link to exact comment
                        comment_url = f"https://reddit.com{post.get('permalink', '')}{top_comment['id']}"
                        answers.append(Answer(
                            platform='reddit',
                            title=post.get('title', ''),
                            url=comment_url,
                            score=r_score,
                            thread_id=post.get('id', ''),
                            answer_id=top_comment['id'],
                            timestamp=post.get('created_utc', 0),
                            preview=f"r/{post.get('subreddit', '')} | top comment",
                            answer_text=top_comment['body'][:200],
                            depth=1,
                        ))
                    else:
                        # Fallback to post URL
                        answers.append(Answer(
                            platform='reddit',
                            title=post.get('title', ''),
                            url=f"https://reddit.com{post.get('permalink', '')}",
                            score=r_score,
                            thread_id=post.get('id', ''),
                            answer_id=post.get('id', ''),
                            timestamp=post.get('created_utc', 0),
                            preview=f"r/{post.get('subreddit', '')} | {post.get('num_comments', 0)} comments",
                            depth=0,
                        ))
        except Exception:
            pass
        return answers

    def _fetch_reddit_top_comment(self, permalink: str) -> Optional[dict]:
        """
        Fetch the top comment from a Reddit post.
        Thread math: post (depth 0) → top comment (depth 1).
        """
        if not permalink:
            return None
        try:
            url = f"https://www.reddit.com{permalink}.json?limit=1&sort=top"
            req = urllib.request.Request(url, headers={
                'User-Agent': 'phi-thread/0.1'
            })
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read())

                if len(data) >= 2:
                    comments = data[1].get('data', {}).get('children', [])
                    for c in comments:
                        if c.get('kind') == 't1':
                            cd = c.get('data', {})
                            if cd.get('body') and cd.get('score', 0) > 1:
                                return {
                                    'id': cd.get('id', ''),
                                    'body': cd.get('body', ''),
                                    'score': cd.get('score', 0),
                                }
        except Exception:
            pass
        return None

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # HN — deep-link to top comment
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def _search_hn(self, query: str, limit: int) -> List[Answer]:
        answers = []
        try:
            # Search for comments (answers) directly, not just stories
            # This finds the actual answers, not just the question/story
            url = (
                f"https://hn.algolia.com/api/v1/search"
                f"?query={query}&hitsPerPage={limit}"
            )
            with urllib.request.urlopen(url, timeout=10) as resp:
                data = json.loads(resp.read())

                for hit in data.get('hits', [])[:limit]:
                    hn_score = (
                        hit.get('points', 0) * 0.05 +
                        hit.get('num_comments', 0) * 0.1
                    )

                    story_id = hit.get('story_id') or hit.get('objectID', '')
                    object_id = hit.get('objectID', '')

                    # If this is a comment (has story_id), link to the comment directly
                    if hit.get('story_id') and hit.get('_tags') and 'comment' in hit.get('_tags', []):
                        hn_url = f"https://news.ycombinator.com/item?id={object_id}"
                        depth = 1
                        title = hit.get('story_title', '') or hit.get('title', '')
                        preview_text = hit.get('comment_text', '')
                        if preview_text:
                            preview_text = self._strip_html(preview_text)[:150]
                    else:
                        hn_url = hit.get('url', '') or f"https://news.ycombinator.com/item?id={object_id}"
                        depth = 0
                        title = hit.get('title', '')
                        preview_text = f"{hit.get('points', 0)} pts | {hit.get('num_comments', 0)} comments"

                    answers.append(Answer(
                        platform='hn',
                        title=title,
                        url=hn_url,
                        score=hn_score,
                        thread_id=str(story_id),
                        answer_id=str(object_id),
                        timestamp=hit.get('created_at_i', 0),
                        preview=preview_text,
                        depth=depth,
                    ))
        except Exception:
            pass
        return answers

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # GITHUB — link to specific issue comment
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def _search_github(self, query: str, limit: int) -> List[Answer]:
        answers = []
        try:
            url = (
                f"https://api.github.com/search/issues"
                f"?q={query}&sort=relevance&per_page={limit}"
            )
            req = urllib.request.Request(url, headers={
                'Accept': 'application/vnd.github.v3+json',
                'User-Agent': 'phi-thread/0.1',
            })
            with urllib.request.urlopen(req, timeout=10) as resp:
                data = json.loads(resp.read())

                for item in data.get('items', [])[:limit]:
                    gh_score = (
                        item.get('comments', 0) * 0.2 +
                        item.get('reactions', {}).get('total_count', 0) * 0.1
                    )

                    # Extract repo name from URL
                    repo_url = item.get('repository_url', '')
                    repo_name = '/'.join(repo_url.split('/')[-2:]) if repo_url else ''

                    answers.append(Answer(
                        platform='github',
                        title=item.get('title', ''),
                        url=item.get('html_url', ''),
                        score=gh_score,
                        thread_id=str(item.get('number', '')),
                        answer_id=str(item.get('number', '')),
                        timestamp=time.time(),
                        preview=repo_name,
                        depth=0,
                    ))
        except Exception:
            pass
        return answers

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # GOOGLE — catches Twitter, blogs, forums, everything
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    def _search_google(self, query: str, limit: int) -> List[Answer]:
        """
        Search via DuckDuckGo (no API key, no blocking).
        Catches Twitter threads, blog posts, forum answers —
        everything that needs API keys on their native platform.
        """
        answers = []
        try:
            # DuckDuckGo HTML search — much friendlier than Google
            search_url = f"https://html.duckduckgo.com/html/?q={query}"
            req = urllib.request.Request(search_url, headers={
                'User-Agent': 'phi-thread/0.1',
            })
            with urllib.request.urlopen(req, timeout=10) as resp:
                page_html = resp.read().decode('utf-8', errors='ignore')

                # DDG pattern: <a class="result__a" href="URL">TITLE</a>
                # and snippet: <a class="result__snippet" ...>SNIPPET</a>
                results = re.findall(
                    r'<a[^>]+class="result__a"[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
                    page_html, re.DOTALL
                )
                snippets = re.findall(
                    r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>',
                    page_html, re.DOTALL
                )

                seen = set()
                for i, (url_raw, title_raw) in enumerate(results[:limit]):
                    # DDG wraps URLs in a redirect — extract actual URL
                    result_url = url_raw
                    if 'uddg=' in result_url:
                        match = re.search(r'uddg=([^&]+)', result_url)
                        if match:
                            result_url = urllib.parse.unquote(match.group(1))

                    result_title = self._strip_html(title_raw)
                    snippet = self._strip_html(snippets[i]) if i < len(snippets) else ''

                    # Skip duplicates and platforms we already search natively
                    if result_url in seen:
                        continue
                    if any(domain in result_url for domain in
                           ['stackoverflow.com', 'reddit.com', 'news.ycombinator.com', 'github.com']):
                        continue

                    seen.add(result_url)

                    # Detect platform from URL
                    platform = 'web'
                    if 'twitter.com' in result_url or 'x.com' in result_url:
                        platform = 'twitter'
                    elif 'dev.to' in result_url:
                        platform = 'devto'
                    elif 'medium.com' in result_url:
                        platform = 'medium'
                    elif 'serverfault.com' in result_url:
                        platform = 'serverfault'
                    elif 'superuser.com' in result_url:
                        platform = 'superuser'
                    elif 'digitalocean.com' in result_url:
                        platform = 'web'
                    elif 'askubuntu.com' in result_url:
                        platform = 'web'

                    answers.append(Answer(
                        platform=platform,
                        title=result_title,
                        url=result_url,
                        score=2.0,
                        thread_id=hashlib.md5(result_url.encode()).hexdigest()[:12],
                        answer_id=hashlib.md5(result_url.encode()).hexdigest()[:12],
                        timestamp=time.time(),
                        preview=snippet[:100] if snippet else f"via web | {platform}",
                        depth=0,
                    ))
        except Exception:
            pass
        return answers

    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
    # HELPERS
    # ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

    @staticmethod
    def _strip_html(text: str) -> str:
        """Remove HTML tags and decode entities."""
        clean = re.sub(r'<[^>]+>', ' ', text)
        clean = html.unescape(clean)
        clean = re.sub(r'\s+', ' ', clean).strip()
        return clean

    @staticmethod
    def _decode_html(text: str) -> str:
        return html.unescape(text)
