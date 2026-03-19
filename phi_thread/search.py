"""
Cross-platform answer search.

Searches Stack Overflow, Reddit, HN, and GitHub for answers
to your question. Auto-indexes results so repeated questions
are instant.
"""

import json
import time
import hashlib
import urllib.request
import urllib.parse
import re
import gzip
from pathlib import Path
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional


@dataclass
class Answer:
    """An answer found on a platform — a coordinate in information space."""
    platform: str
    title: str
    url: str
    score: float = 0.0
    thread_id: str = ""
    timestamp: float = 0.0
    preview: str = ""

    @property
    def hash(self) -> str:
        return hashlib.sha256(f"{self.platform}:{self.url}".encode()).hexdigest()[:12]


class ThreadSearch:
    """
    Search across platforms for existing answers.
    The KB builds itself — first ask is live, second is cached.
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

    def _cache_key(self, question: str) -> str:
        normalized = re.sub(r'\s+', ' ', question.lower().strip())
        return hashlib.sha256(normalized.encode()).hexdigest()[:16]

    def _get_cached(self, question: str) -> Optional[List[Answer]]:
        key = self._cache_key(question)
        cache_file = self.CACHE_DIR / f"{key}.json"
        if cache_file.exists():
            try:
                data = json.loads(cache_file.read_text())
                # Cache valid for 24 hours
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
        Search for answers. Returns cached if available, else searches live.
        """
        # Check cache first
        cached = self._get_cached(question)
        if cached:
            return cached[:max_results]

        if platforms is None:
            platforms = ['stackoverflow', 'reddit', 'hn', 'github']

        answers = []
        query = urllib.parse.quote_plus(question)

        if 'stackoverflow' in platforms:
            answers.extend(self._search_stackoverflow(query, max_results))

        if 'reddit' in platforms:
            answers.extend(self._search_reddit(query, max_results))

        if 'hn' in platforms:
            answers.extend(self._search_hn(query, max_results))

        if 'github' in platforms:
            answers.extend(self._search_github(query, max_results))

        # Re-rank by score * title relevance
        query_words = set(re.findall(r'\w+', question.lower()))
        query_words -= {'the', 'a', 'an', 'is', 'are', 'how', 'do', 'i', 'to',
                        'my', 'in', 'on', 'with', 'for', 'and', 'or', 'not', 'what',
                        'why', 'when', 'can', 'does', 'keep', 'keeps', 'it'}
        for answer in answers:
            title_words = set(re.findall(r'\w+', answer.title.lower()))
            if query_words:
                overlap = len(query_words & title_words) / len(query_words)
            else:
                overlap = 0.5
            # Multiply score by relevance (0.1 floor so irrelevant results sink)
            answer.score *= max(0.1, overlap)

        answers.sort(key=lambda a: a.score, reverse=True)
        answers = answers[:max_results]

        # Cache results
        if answers:
            self._set_cache(question, answers)

        return answers

    def _search_stackoverflow(self, query: str, limit: int) -> List[Answer]:
        answers = []
        try:
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

                for item in data.get('items', [])[:limit]:
                    if item.get('is_answered'):
                        # SO answers are high-signal: boost base score
                        so_score = 5.0 + (
                            item.get('answer_count', 0) * 1.5 +
                            item.get('view_count', 0) / 5000 +
                            item.get('score', 0) * 0.5
                        )
                        answers.append(Answer(
                            platform='stackoverflow',
                            title=self._decode_html(item.get('title', '')),
                            url=item.get('link', ''),
                            score=so_score,
                            thread_id=str(item['question_id']),
                            timestamp=item.get('creation_date', 0),
                            preview=', '.join(item.get('tags', [])[:5]),
                        ))
        except Exception as e:
            pass  # Silent fail — other platforms may work
        return answers

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

                for child in data.get('data', {}).get('children', [])[:limit]:
                    post = child.get('data', {})
                    if post.get('num_comments', 0) > 0:
                        # Score: upvotes + comments * 2
                        r_score = (
                            post.get('score', 0) * 0.01 +
                            post.get('num_comments', 0) * 0.1
                        )
                        answers.append(Answer(
                            platform='reddit',
                            title=post.get('title', ''),
                            url=f"https://reddit.com{post.get('permalink', '')}",
                            score=r_score,
                            thread_id=post.get('id', ''),
                            timestamp=post.get('created_utc', 0),
                            preview=f"r/{post.get('subreddit', '')} | {post.get('num_comments', 0)} comments",
                        ))
        except Exception:
            pass
        return answers

    def _search_hn(self, query: str, limit: int) -> List[Answer]:
        answers = []
        try:
            url = (
                f"https://hn.algolia.com/api/v1/search"
                f"?query={query}&tags=story&hitsPerPage={limit}"
            )
            with urllib.request.urlopen(url, timeout=10) as resp:
                data = json.loads(resp.read())

                for hit in data.get('hits', [])[:limit]:
                    # Score: points + comments
                    hn_score = (
                        hit.get('points', 0) * 0.05 +
                        hit.get('num_comments', 0) * 0.1
                    )
                    hn_url = hit.get('url', '') or f"https://news.ycombinator.com/item?id={hit.get('objectID', '')}"
                    answers.append(Answer(
                        platform='hn',
                        title=hit.get('title', ''),
                        url=hn_url,
                        score=hn_score,
                        thread_id=hit.get('objectID', ''),
                        timestamp=hit.get('created_at_i', 0),
                        preview=f"{hit.get('points', 0)} points | {hit.get('num_comments', 0)} comments",
                    ))
        except Exception:
            pass
        return answers

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
                    answers.append(Answer(
                        platform='github',
                        title=item.get('title', ''),
                        url=item.get('html_url', ''),
                        score=gh_score,
                        thread_id=str(item.get('number', '')),
                        timestamp=time.time(),
                        preview=item.get('repository_url', '').split('/')[-1] if item.get('repository_url') else '',
                    ))
        except Exception:
            pass
        return answers

    @staticmethod
    def _decode_html(text: str) -> str:
        """Decode HTML entities in SO titles."""
        import html
        return html.unescape(text)
