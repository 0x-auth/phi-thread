#!/usr/bin/env python3
"""
Tests for phi-thread.

Run: python3 test_phi_thread.py
  or: python3 -m pytest test_phi_thread.py -v
"""

import time
import shutil
from pathlib import Path
from phi_thread.search import ThreadSearch, Answer


# Use temp cache dir so tests don't pollute real cache
TEST_CACHE = Path("/tmp/phi-thread-test-cache")


def get_test_searcher():
    """Create a searcher with isolated test cache."""
    if TEST_CACHE.exists():
        shutil.rmtree(TEST_CACHE)
    TEST_CACHE.mkdir(parents=True)
    searcher = ThreadSearch()
    searcher.CACHE_DIR = TEST_CACHE / "cache"
    searcher.CACHE_DIR.mkdir()
    searcher.INDEX_PATH = TEST_CACHE / "index.json"
    return searcher


def test_stackoverflow_search():
    """Test that SO search returns relevant results."""
    s = get_test_searcher()
    answers = s._search_stackoverflow("docker+container+keeps+restarting", 5)
    assert len(answers) > 0, "SO should return results for docker query"
    assert all(a.platform == 'stackoverflow' for a in answers)
    assert all(a.url.startswith('https://stackoverflow.com') for a in answers)
    # At least one result should mention docker in title
    titles = ' '.join(a.title.lower() for a in answers)
    assert 'docker' in titles, f"Expected 'docker' in titles, got: {titles}"
    print(f"  SO: {len(answers)} results, top: {answers[0].title[:60]}")


def test_reddit_search():
    """Test that Reddit search returns results."""
    s = get_test_searcher()
    answers = s._search_reddit("nginx+reverse+proxy", 5)
    assert len(answers) > 0, "Reddit should return results for nginx query"
    assert all(a.platform == 'reddit' for a in answers)
    assert all('reddit.com' in a.url for a in answers)
    print(f"  Reddit: {len(answers)} results, top: {answers[0].title[:60]}")


def test_hn_search():
    """Test that HN Algolia search returns results."""
    s = get_test_searcher()
    answers = s._search_hn("python+asyncio", 5)
    assert len(answers) > 0, "HN should return results for python query"
    assert all(a.platform == 'hn' for a in answers)
    print(f"  HN: {len(answers)} results, top: {answers[0].title[:60]}")


def test_github_search():
    """Test that GitHub search returns results."""
    s = get_test_searcher()
    answers = s._search_github("kubernetes+crashloopbackoff", 3)
    assert len(answers) > 0, "GitHub should return results for k8s query"
    assert all(a.platform == 'github' for a in answers)
    assert all('github.com' in a.url for a in answers)
    print(f"  GitHub: {len(answers)} results, top: {answers[0].title[:60]}")


def test_caching():
    """Test that results are cached and second call is fast."""
    s = get_test_searcher()

    # First call — live (slow)
    t1 = time.time()
    results1 = s.search("python asyncio gather", platforms=['stackoverflow'], max_results=3)
    elapsed1 = time.time() - t1

    assert len(results1) > 0, "Should get results"

    # Second call — cached (fast)
    t2 = time.time()
    results2 = s.search("python asyncio gather", platforms=['stackoverflow'], max_results=3)
    elapsed2 = time.time() - t2

    assert len(results2) == len(results1), "Cached results should match"
    assert results2[0].url == results1[0].url, "Same top result"
    assert elapsed2 < 0.1, f"Cached call should be <100ms, was {elapsed2:.3f}s"

    print(f"  Live: {elapsed1:.2f}s, Cached: {elapsed2:.4f}s")


def test_relevance_ranking():
    """Test that title relevance affects ranking."""
    s = get_test_searcher()
    results = s.search("docker container keeps restarting", platforms=['stackoverflow', 'reddit'], max_results=5)

    if len(results) >= 2:
        # Top result should have 'docker' and 'container' or 'restarting' in title
        top_title = results[0].title.lower()
        assert 'docker' in top_title or 'container' in top_title, \
            f"Top result should be relevant, got: {results[0].title}"
        print(f"  Top result: {results[0].title[:60]}")


def test_search_combined():
    """Test full search across all platforms."""
    s = get_test_searcher()
    results = s.search("vault 403 forbidden", max_results=10)

    platforms_found = set(a.platform for a in results)
    print(f"  Platforms: {platforms_found}")
    print(f"  Total results: {len(results)}")
    for r in results[:3]:
        print(f"    [{r.platform}] {r.title[:50]}  (score={r.score:.2f})")

    assert len(results) > 0, "Should find results across platforms"


def test_json_output():
    """Test that Answer dataclass is JSON-serializable."""
    from dataclasses import asdict
    import json

    a = Answer(
        platform='stackoverflow',
        title='Test answer',
        url='https://stackoverflow.com/q/123',
        score=5.0,
        thread_id='123',
        timestamp=time.time(),
        preview='python, docker',
    )
    j = json.dumps(asdict(a))
    assert 'stackoverflow' in j
    assert 'Test answer' in j
    print(f"  JSON: {j[:80]}...")


def test_empty_query():
    """Test that empty/short queries don't crash."""
    s = get_test_searcher()
    results = s.search("x", platforms=['stackoverflow'], max_results=3)
    # Should return something or empty list, but not crash
    print(f"  Short query: {len(results)} results")


if __name__ == "__main__":
    tests = [
        ("Stack Overflow search", test_stackoverflow_search),
        ("Reddit search", test_reddit_search),
        ("HN search", test_hn_search),
        ("GitHub search", test_github_search),
        ("Caching", test_caching),
        ("Relevance ranking", test_relevance_ranking),
        ("Combined search", test_search_combined),
        ("JSON output", test_json_output),
        ("Empty query", test_empty_query),
    ]

    print("=" * 60)
    print("  phi-thread tests")
    print("=" * 60)

    passed = 0
    failed = 0

    for name, fn in tests:
        try:
            print(f"\n[TEST] {name}")
            fn()
            print(f"  PASS")
            passed += 1
        except Exception as e:
            print(f"  FAIL: {e}")
            failed += 1

    print(f"\n{'=' * 60}")
    print(f"  {passed} passed, {failed} failed")
    print(f"{'=' * 60}")

    # Cleanup
    if TEST_CACHE.exists():
        shutil.rmtree(TEST_CACHE)
