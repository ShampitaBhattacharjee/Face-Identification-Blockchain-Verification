import json
from pathlib import Path

from faceid.search import (
    Match,
    domain_of,
    is_social,
    load_fixture_result,
    looks_like_post,
    parse_bing_visual_search,
    parse_google_lens,
    rank_matches,
)

FIXTURE = Path(__file__).parent / "fixtures" / "serpapi_google_lens.json"


def test_domain_of_strips_subdomains_and_ports():
    assert domain_of("https://www.instagram.com/p/abc") == "instagram.com"
    assert domain_of("https://m.facebook.com:443/x") == "facebook.com"


def test_is_social():
    assert is_social("https://x.com/a/status/1")
    assert is_social("https://www.linkedin.com/posts/foo")
    assert not is_social("https://news.example.com/article")


def test_looks_like_post():
    assert looks_like_post("https://x.com/a/status/1234")
    assert looks_like_post("https://www.instagram.com/p/CxYz/")
    assert looks_like_post("https://www.tiktok.com/@user/video/7000000000000000000")
    assert looks_like_post("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    assert not looks_like_post("https://www.instagram.com/janedoe/")


def test_parse_google_lens_fixture():
    payload = json.loads(FIXTURE.read_text())
    matches = parse_google_lens(payload)
    assert len(matches) == 6
    assert all(m.provider == "google_lens:visual_matches" for m in matches)


def test_rank_prefers_social_posts_and_dedupes():
    payload = json.loads(FIXTURE.read_text())
    ranked = rank_matches(parse_google_lens(payload))
    assert len(ranked) == 5  # trailing-slash duplicate removed
    assert ranked[0].url == "https://x.com/janedoe/status/1234567890123456789"
    assert ranked[0].is_social and ranked[0].is_post
    assert ranked[1].url == "https://www.instagram.com/p/CxYz123AbC/"
    assert ranked[2].url == "https://www.instagram.com/janedoe/"
    assert not ranked[-1].is_social


def test_fixture_result_is_flagged_dry_run():
    result = load_fixture_result(FIXTURE)
    assert result.dry_run is True
    assert result.best_social().domain == "x.com"
    assert result.to_dict()["social_matches"] == 3


def test_parse_bing_visual_search():
    payload = {
        "tags": [
            {
                "actions": [
                    {
                        "actionType": "PagesIncluding",
                        "data": {
                            "value": [
                                {
                                    "name": "A post",
                                    "hostPageUrl": "https://www.facebook.com/user/posts/123",
                                    "thumbnailUrl": "https://tse.mm.bing.net/th?id=1",
                                }
                            ]
                        },
                    },
                    {"actionType": "MoreSizes", "data": {"value": [{"hostPageUrl": "x"}]}},
                ]
            }
        ]
    }
    matches = rank_matches(parse_bing_visual_search(payload))
    assert len(matches) == 1
    assert matches[0].is_social and matches[0].is_post


def test_score_ordering_by_position_within_same_class():
    a = Match(url="https://x.com/a/status/1", title="", provider="p", position=1)
    b = Match(url="https://x.com/b/status/2", title="", provider="p", position=9)
    ranked = rank_matches([b, a])
    assert [m.url for m in ranked] == [a.url, b.url]
