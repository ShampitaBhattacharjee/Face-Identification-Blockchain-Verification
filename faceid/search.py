"""Stage 2: genuine reverse-image search.

Providers (all live HTTP calls, nothing is hardcoded):
  * google_lens - SerpApi `engine=google_lens` (visual_matches + exact_matches)
  * yandex      - SerpApi `engine=yandex_images` (strong on faces)
  * bing        - Microsoft Bing Visual Search REST API (needs BING_API_KEY)

URL-based engines need the query image to be publicly reachable, so the image is
uploaded to a short-lived anonymous host first (or pass your own --image-url).
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

import requests

log = logging.getLogger(__name__)

USER_AGENT = (
    "face-id-blockchain-verification/1.0 "
    "(+https://gitlab.com/hhgoa-group/face-id-blockchain-verification)"
)
SERPAPI_ENDPOINT = "https://serpapi.com/search.json"
SEARCHAPI_ENDPOINT = "https://www.searchapi.io/api/v1/search"
BING_ENDPOINT = "https://api.bing.microsoft.com/v7.0/images/visualsearch"
DEFAULT_PROVIDERS: tuple[str, ...] = ("google_lens", "yandex", "bing")

SOCIAL_DOMAINS: frozenset[str] = frozenset(
    {
        "x.com",
        "twitter.com",
        "instagram.com",
        "facebook.com",
        "fb.com",
        "linkedin.com",
        "tiktok.com",
        "threads.net",
        "reddit.com",
        "pinterest.com",
        "youtube.com",
        "youtu.be",
        "vk.com",
        "tumblr.com",
        "snapchat.com",
        "mastodon.social",
        "bsky.app",
    }
)

POST_PATTERNS: tuple[re.Pattern[str], ...] = tuple(
    re.compile(p, re.IGNORECASE)
    for p in (
        r"/status/\d+",  # X / Twitter
        r"/p/[\w-]+",  # Instagram post
        r"/reels?/[\w-]+",  # Instagram reel
        r"/posts/",  # LinkedIn / Facebook
        r"/feed/update/",  # LinkedIn
        r"/@[\w.]+/video/\d+",  # TikTok
        r"/video/\d+",  # TikTok / Facebook
        r"[?&]v=[\w-]+",  # YouTube
        r"/shorts/[\w-]+",  # YouTube shorts
        r"/pin/\d+",  # Pinterest
        r"/comments/\w+",  # Reddit
        r"/photo(s)?/",  # Facebook photo
        r"/permalink\.php",  # Facebook
        r"/profile/[\w.]+/post/",  # Bluesky
        r"/post/\d+",  # Tumblr / Threads
    )
)


class SearchError(RuntimeError):
    """Any provider, upload or parsing failure."""


class MissingApiKeyError(SearchError):
    """No search provider credentials configured."""


@dataclass
class Match:
    url: str
    title: str
    provider: str
    position: int
    domain: str = ""
    thumbnail: str | None = None
    source: str | None = None
    is_social: bool = False
    is_post: bool = False
    score: float = 0.0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def domain_of(url: str) -> str:
    host = (urlparse(url).netloc or "").lower().split(":")[0]
    for prefix in ("www.", "m.", "mobile.", "amp."):
        if host.startswith(prefix):
            host = host[len(prefix) :]
    return host


def is_social(url: str) -> bool:
    host = domain_of(url)
    return any(host == d or host.endswith("." + d) for d in SOCIAL_DOMAINS)


def looks_like_post(url: str) -> bool:
    return any(p.search(url) for p in POST_PATTERNS)


def score_match(match: Match) -> float:
    """Higher is better: social post > social profile > everything else, then by rank."""
    score = 0.0
    if match.is_social:
        score += 10.0
    if match.is_post:
        score += 5.0
    if match.is_social and match.is_post:
        score += 5.0
    score -= min(match.position, 50) * 0.1
    return round(score, 3)


def annotate(match: Match) -> Match:
    match.domain = domain_of(match.url)
    match.is_social = is_social(match.url)
    match.is_post = looks_like_post(match.url)
    match.score = score_match(match)
    return match


def rank_matches(matches: Iterable[Match]) -> list[Match]:
    seen: set[str] = set()
    unique: list[Match] = []
    for m in matches:
        key = m.url.rstrip("/").lower()
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(annotate(m))
    return sorted(unique, key=lambda m: (-m.score, m.position))


#  parsers


def parse_google_lens(payload: dict[str, Any], provider: str = "google_lens") -> list[Match]:
    matches: list[Match] = []
    for key in ("exact_matches", "visual_matches"):
        for i, item in enumerate(payload.get(key) or []):
            link = item.get("link")
            if not link:
                continue
            matches.append(
                Match(
                    url=link,
                    title=item.get("title") or "",
                    provider=f"{provider}:{key}",
                    position=int(item.get("position", i + 1)),
                    thumbnail=item.get("thumbnail"),
                    source=item.get("source"),
                )
            )
    kg = payload.get("knowledge_graph") or []
    if isinstance(kg, dict):
        kg = [kg]
    for i, item in enumerate(kg):
        link = item.get("link")
        if link:
            matches.append(
                Match(
                    url=link,
                    title=item.get("title") or "",
                    provider=f"{provider}:knowledge_graph",
                    position=i + 1,
                    thumbnail=item.get("thumbnail"),
                    source="Google Knowledge Graph",
                )
            )
    return matches


def parse_yandex(payload: dict[str, Any], provider: str = "yandex") -> list[Match]:
    if "visual_matches" in payload:
        return parse_google_lens(payload, provider=provider)
    matches: list[Match] = []
    for i, item in enumerate(payload.get("image_results") or []):
        link = item.get("link") or (item.get("source") or {}).get("link")
        if not link:
            continue
        source = item.get("source")
        matches.append(
            Match(
                url=link,
                title=item.get("title") or "",
                provider=provider,
                position=int(item.get("position", i + 1)),
                thumbnail=(item.get("thumbnail") or {}).get("link")
                if isinstance(item.get("thumbnail"), dict)
                else item.get("thumbnail"),
                source=source.get("name") if isinstance(source, dict) else source,
            )
        )
    return matches


def parse_bing_visual_search(payload: dict[str, Any], provider: str = "bing") -> list[Match]:
    matches: list[Match] = []
    for tag in payload.get("tags") or []:
        for action in tag.get("actions") or []:
            if action.get("actionType") not in ("PagesIncluding", "VisualSearch"):
                continue
            for i, item in enumerate((action.get("data") or {}).get("value") or []):
                link = item.get("hostPageUrl")
                if not link:
                    continue
                matches.append(
                    Match(
                        url=link,
                        title=item.get("name") or "",
                        provider=f"{provider}:{action['actionType']}",
                        position=i + 1,
                        thumbnail=item.get("thumbnailUrl"),
                        source=item.get("hostPageDisplayUrl"),
                    )
                )
    return matches


#  upload


class ImageHost:
    """Upload a local image to a short-lived anonymous host so URL engines can fetch it."""

    HOSTS: tuple[str, ...] = ("freeimage", "tmpfiles", "litterbox", "0x0")

    def __init__(self, session: requests.Session, preferred: str | None = None) -> None:
        self.session = session
        order = list(self.HOSTS)
        if preferred and preferred in order:
            order.remove(preferred)
            order.insert(0, preferred)
        self.order = order

    def upload(self, path: str | Path) -> str:
        path = Path(path)
        errors: list[str] = []
        for name in self.order:
            uploader = getattr(self, f"_upload_{name}")
            try:
                url = uploader(path)
                log.info("Uploaded %s to %s -> %s", path.name, name, url)
                return url
            except Exception as exc:  # noqa: BLE001 - try the next host
                errors.append(f"{name}: {exc}")
        raise SearchError(
            "Could not upload the image to any temporary host:\n  "
            + "\n  ".join(errors)
            + "\nTip: host the image yourself and pass --image-url."
        )

    def _upload_freeimage(self, path: Path) -> str:
        with path.open("rb") as fh:
            resp = self.session.post(
                "https://freeimage.host/api/1/upload",
                data={"key": "6d207e02198a847aa98d0a2a901485a5", "action": "upload", "format": "json"},
                files={"source": (path.name, fh)},
                timeout=60,
            )
        resp.raise_for_status()
        url = resp.json().get("image", {}).get("url")
        if not url or not url.startswith("http"):
            raise SearchError("freeimage.host did not return a valid URL")
        return url

    def _upload_litterbox(self, path: Path) -> str:
        with path.open("rb") as fh:
            resp = self.session.post(
                "https://litterbox.catbox.moe/resources/internals/api.php",
                data={"reqtype": "fileupload", "time": "1h"},
                files={"fileToUpload": (path.name, fh)},
                timeout=60,
            )
        resp.raise_for_status()
        url = resp.text.strip()
        if not url.startswith("http"):
            raise SearchError(f"unexpected response: {url[:80]}")
        return url

    def _upload_tmpfiles(self, path: Path) -> str:
        with path.open("rb") as fh:
            resp = self.session.post(
                "https://tmpfiles.org/api/v1/upload", files={"file": (path.name, fh)}, timeout=60
            )
        resp.raise_for_status()
        url = resp.json()["data"]["url"]
        return url.replace("https://tmpfiles.org/", "https://tmpfiles.org/dl/", 1)

    def _upload_0x0(self, path: Path) -> str:
        with path.open("rb") as fh:
            resp = self.session.post(
                "https://0x0.st",
                data={"expires": "1"},
                files={"file": (path.name, fh)},
                timeout=60,
            )
        resp.raise_for_status()
        url = resp.text.strip()
        if not url.startswith("http"):
            raise SearchError(f"unexpected response: {url[:80]}")
        return url


# searcher


@dataclass
class SearchResult:
    image_url: str
    matches: list[Match]
    providers_used: list[str]
    raw_files: list[str]
    dry_run: bool = False

    def social_matches(self) -> list[Match]:
        return [m for m in self.matches if m.is_social]

    def best_social(self) -> Match | None:
        social = self.social_matches()
        return social[0] if social else None

    def to_dict(self) -> dict[str, Any]:
        return {
            "image_url": self.image_url,
            "providers_used": self.providers_used,
            "raw_files": self.raw_files,
            "dry_run": self.dry_run,
            "total_matches": len(self.matches),
            "social_matches": len(self.social_matches()),
            "matches": [m.to_dict() for m in self.matches],
        }


class ReverseImageSearcher:
    def __init__(
        self,
        serpapi_key: str | None,
        bing_key: str | None = None,
        output_dir: str | Path = "output",
        session: requests.Session | None = None,
        preferred_host: str | None = None,
    ) -> None:
        self.serpapi_key = serpapi_key
        self.bing_key = bing_key
        self.output_dir = Path(output_dir)
        self.session = session or requests.Session()
        self.session.headers.setdefault("User-Agent", USER_AGENT)
        self.image_host = ImageHost(self.session, preferred_host)

    #  public API 

    def search(
        self,
        image_path: str | Path,
        image_url: str | None = None,
        providers: Iterable[str] = DEFAULT_PROVIDERS,
    ) -> SearchResult:
        providers = [p.strip().lower() for p in providers if p.strip()]
        needs_serpapi = any(p in ("google_lens", "yandex") for p in providers)
        if needs_serpapi and not self.serpapi_key and not self.bing_key:
            raise MissingApiKeyError(
                "SERPAPI_KEY is not set (and no BING_API_KEY fallback). "
                "Get a free key at https://serpapi.com and add it to .env"
            )

        if image_url is None and needs_serpapi and self.serpapi_key:
            image_url = self.image_host.upload(image_path)

        matches: list[Match] = []
        used: list[str] = []
        raws: list[str] = []
        for provider in providers:
            try:
                if provider == "google_lens" and self.serpapi_key and image_url:
                    for lens_type in ("visual_matches", "exact_matches"):
                        payload = self._serpapi(
                            {"engine": "google_lens", "url": image_url, "type": lens_type, "hl": "en"}
                        )
                        raws.append(self._save_raw(f"google_lens_{lens_type}", payload))
                        matches.extend(parse_google_lens(payload))
                        used.append(f"google_lens/{lens_type}")
                elif provider == "yandex" and self.serpapi_key and image_url:
                    payload = self._serpapi({"engine": "yandex_images", "url": image_url})
                    raws.append(self._save_raw("yandex_images", payload))
                    matches.extend(parse_yandex(payload))
                    used.append("yandex")
                elif provider == "bing":
                    if not self.bing_key:
                        log.info("Skipping bing: BING_API_KEY not set")
                        continue
                    payload = self._bing(Path(image_path))
                    raws.append(self._save_raw("bing_visual_search", payload))
                    matches.extend(parse_bing_visual_search(payload))
                    used.append("bing")
                else:
                    log.info("Skipping provider %s (not configured)", provider)
            except SearchError as exc:
                log.warning("Provider %s failed: %s", provider, exc)
            except requests.RequestException as exc:
                log.warning("Provider %s network error: %s", provider, exc)

        if not used:
            raise SearchError(
                "No search provider produced a response. Check your API keys, quota and network."
            )
        return SearchResult(
            image_url=image_url or f"file://{Path(image_path).resolve()}",
            matches=rank_matches(matches),
            providers_used=used,
            raw_files=raws,
        )

    #  providers 

    def _serpapi(self, params: dict[str, str]) -> dict[str, Any]:
        key = (self.serpapi_key or "").strip()
        is_searchapi_io = len(key) != 64  # SearchApi.io keys are 24 chars, SerpApi keys are 64 hex chars
        p = dict(params)
        if is_searchapi_io:
            endpoint = SEARCHAPI_ENDPOINT
            if p.get("engine") == "yandex_images":
                p["engine"] = "yandex_reverse_image"
            if p.get("engine") == "google_lens" and p.get("type") == "exact_matches":
                return {}
            p["api_key"] = key
        else:
            endpoint = SERPAPI_ENDPOINT
            p["api_key"] = key

        resp = self.session.get(endpoint, params=p, timeout=120)
        provider_name = "SearchApi.io" if is_searchapi_io else "SerpApi"
        if resp.status_code == 401:
            raise SearchError(f"{provider_name} rejected the API key (401)")
        if resp.status_code == 429:
            raise SearchError(f"{provider_name} quota exhausted (429) - free tier is 100 searches/month")
        try:
            payload = resp.json()
        except ValueError as exc:
            raise SearchError(f"{provider_name} returned non-JSON (HTTP {resp.status_code})") from exc
        error = payload.get("error")
        if error:
            if "hasn't returned any results" in error or "didn't return any results" in error:
                log.info("%s %s: no results (%s)", provider_name, p.get("engine"), error)
                return {}
            raise SearchError(f"{provider_name} error: {error}")
        if resp.status_code != 200:
            raise SearchError(f"{provider_name} HTTP {resp.status_code}")
        return payload

    def _bing(self, image_path: Path) -> dict[str, Any]:
        with image_path.open("rb") as fh:
            resp = self.session.post(
                BING_ENDPOINT,
                headers={"Ocp-Apim-Subscription-Key": self.bing_key or ""},
                files={"image": (image_path.name, fh)},
                timeout=120,
            )
        if resp.status_code != 200:
            raise SearchError(f"Bing Visual Search HTTP {resp.status_code}: {resp.text[:200]}")
        return resp.json()

    def _save_raw(self, name: str, payload: dict[str, Any]) -> str:
        self.output_dir.mkdir(parents=True, exist_ok=True)
        path = self.output_dir / f"raw_{name}.json"
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        return str(path)


def load_fixture_result(fixture_path: str | Path) -> SearchResult:
    """TESTING ONLY - build a SearchResult from a saved SerpApi response."""
    path = Path(fixture_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    return SearchResult(
        image_url=f"fixture://{path.name}",
        matches=rank_matches(parse_google_lens(payload, provider="FIXTURE")),
        providers_used=["fixture"],
        raw_files=[str(path)],
        dry_run=True,
    )
