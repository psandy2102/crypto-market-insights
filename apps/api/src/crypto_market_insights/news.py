"""RSS normalization, canonicalization, deduplication, and feed polling."""

import hashlib
import time
import xml.etree.ElementTree as ElementTree
from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
from email.utils import parsedate_to_datetime
from typing import Protocol
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, field_validator

NEWS_STRATEGY_VERSION = "rss-ingestion-v1"
TRACKING_PARAMETERS = {
    "fbclid",
    "gclid",
    "mc_cid",
    "mc_eid",
    "ref",
    "source",
    "utm_campaign",
    "utm_content",
    "utm_medium",
    "utm_source",
    "utm_term",
}


class NewsArticle(BaseModel):
    """One normalized article, with permitted excerpt and provenance."""

    model_config = ConfigDict(frozen=True)

    canonical_url: str = Field(min_length=1)
    source_url: str = Field(min_length=1)
    title: str = Field(min_length=1)
    publisher: str = Field(min_length=1)
    language: str = Field(default="unknown", min_length=2, max_length=35)
    published_at: datetime | None = None
    retrieved_at: datetime
    excerpt: str | None = None
    feed_id: str = Field(min_length=1)

    @field_validator("published_at", "retrieved_at")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None:
            if value.tzinfo is None or value.utcoffset() is None:
                raise ValueError("Article timestamps must include a timezone.")
            return value.astimezone(UTC)
        return value


class NewsFeedRun(BaseModel):
    """Visible outcome of one feed polling attempt."""

    model_config = ConfigDict(frozen=True)

    feed_id: str
    status: str
    started_at: datetime
    completed_at: datetime | None
    articles_received: int = Field(default=0, ge=0)
    articles_persisted: int = Field(default=0, ge=0)
    canonical_articles_added: int = Field(default=0, ge=0)
    duplicates_collapsed: int = Field(default=0, ge=0)
    error_code: str | None = None
    error_message: str | None = None


class NewsHealth(BaseModel):
    """Provider/feed freshness and failure state."""

    model_config = ConfigDict(frozen=True)

    feed_id: str
    url: str
    status: str
    last_attempt_at: datetime
    last_success_at: datetime | None
    last_error: str | None
    stale: bool
    stale_after: timedelta


class NewsRepositoryProtocol(Protocol):
    def start_feed_run(self, feed_id: str, url: str, started_at: datetime) -> str: ...

    def persist_article(self, article: NewsArticle) -> bool: ...

    def complete_feed_run(
        self,
        run_id: str,
        *,
        articles_received: int,
        articles_persisted: int,
        canonical_articles_added: int,
        duplicates_collapsed: int,
    ) -> None: ...

    def fail_feed_run(
        self,
        run_id: str,
        *,
        error_code: str,
        error_message: str,
    ) -> None: ...


def canonicalize_url(value: str) -> str:
    """Return a stable HTTP(S) article URL for source deduplication."""
    raw = value.strip()
    if not raw:
        raise ValueError("Article URL cannot be empty.")
    split = urlsplit(raw)
    if split.scheme not in {"http", "https"} or not split.netloc:
        raise ValueError("Article URL must be absolute HTTP(S).")
    host = split.hostname or ""
    if host.startswith("www."):
        host = host[4:]
    host = host.lower()
    port = split.port
    netloc = f"{host}:{port}" if port is not None else host
    query = [
        (key.lower(), item)
        for key, item in parse_qsl(split.query, keep_blank_values=False)
        if key.lower() not in TRACKING_PARAMETERS
    ]
    query.sort()
    return urlunsplit((split.scheme.lower(), netloc, split.path or "/", urlencode(query), ""))


def title_fingerprint(title: str, publisher: str) -> str:
    normalized = " ".join(title.lower().split())
    normalized_publisher = " ".join(publisher.lower().split())
    return hashlib.sha256(f"{normalized_publisher}|{normalized}".encode()).hexdigest()


def parse_feed_xml(
    payload: bytes,
    *,
    feed_id: str,
    retrieved_at: datetime,
    allowed_excerpt_chars: int = 500,
) -> list[NewsArticle]:
    """Parse RSS 2.0 or Atom XML without executing feed-provided content."""
    if retrieved_at.tzinfo is None or retrieved_at.utcoffset() is None:
        raise ValueError("retrieved_at must include a timezone.")
    try:
        root = ElementTree.fromstring(payload)
    except ElementTree.ParseError as error:
        raise NewsProviderError(
            "The feed returned invalid XML.",
            provider="rss",
            feed_id=feed_id,
            error_code="invalid_feed_xml",
            retryable=False,
        ) from error

    namespace = ""
    if root.tag.startswith("{"):
        namespace = root.tag.split("}", 1)[0] + "}"

    articles: list[NewsArticle] = []
    if root.tag.endswith("feed"):
        entries = root.findall(f"{namespace}entry")
        for entry in entries:
            title = _xml_text(entry, namespace, "title")
            link = _atom_link(entry, namespace)
            publisher = _xml_text(entry, namespace, "author") or _xml_text(root, namespace, "title")
            published_text = _xml_text(entry, namespace, "published") or _xml_text(
                entry, namespace, "updated"
            )
            excerpt = _xml_text(entry, namespace, "summary") or _xml_text(
                entry, namespace, "content"
            )
            articles.append(
                _build_article(
                    feed_id=feed_id,
                    title=title,
                    link=link,
                    publisher=publisher,
                    published_text=published_text,
                    excerpt=excerpt,
                    retrieved_at=retrieved_at,
                    allowed_excerpt_chars=allowed_excerpt_chars,
                )
            )
    else:
        channel_element = root.find("channel")
        channel = channel_element if channel_element is not None else root
        channel_title = _xml_text(channel, "", "title")
        for item in channel.findall(".//item"):
            articles.append(
                _build_article(
                    feed_id=feed_id,
                    title=_xml_text(item, "", "title"),
                    link=_xml_text(item, "", "link") or _xml_text(item, "", "guid"),
                    publisher=_xml_text(item, "", "dc:creator")
                    or _xml_text(item, "", "author")
                    or channel_title,
                    published_text=_xml_text(item, "", "pubDate")
                    or _xml_text(item, "", "published"),
                    excerpt=_xml_text(item, "", "description")
                    or _xml_text(item, "", "summary")
                    or _xml_text(item, "", "encoded"),
                    retrieved_at=retrieved_at,
                    allowed_excerpt_chars=allowed_excerpt_chars,
                )
            )
    return articles


def _xml_text(parent: ElementTree.Element, namespace: str, name: str) -> str:
    element = parent.find(f"{namespace}{name}")
    if element is None and ":" in name:
        prefix, local = name.split(":", 1)
        element = parent.find(f".//{{http://purl.org/dc/elements/1.1/}}{local}")
        if element is None:
            element = parent.find(f".//{local}")
    if element is None:
        return ""
    return "".join(element.itertext()).strip()


def _atom_link(entry: ElementTree.Element, namespace: str) -> str:
    for link in entry.findall(f"{namespace}link"):
        href = link.get("href", "").strip()
        if href and link.get("rel", "alternate") in {"alternate", ""}:
            return href
    return ""


def _parse_published(value: str) -> datetime | None:
    if not value:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError, OverflowError):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _build_article(
    *,
    feed_id: str,
    title: str,
    link: str,
    publisher: str,
    published_text: str,
    excerpt: str,
    retrieved_at: datetime,
    allowed_excerpt_chars: int,
) -> NewsArticle:
    if not title or not link:
        raise NewsProviderError(
            "A feed item is missing a title or link.",
            provider="rss",
            feed_id=feed_id,
            error_code="invalid_feed_item",
            retryable=False,
        )
    canonical = canonicalize_url(link)
    clean_excerpt = " ".join(excerpt.split())
    if len(clean_excerpt) > allowed_excerpt_chars:
        clean_excerpt = clean_excerpt[:allowed_excerpt_chars].rstrip() + "..."
    return NewsArticle(
        canonical_url=canonical,
        source_url=link.strip(),
        title=title,
        publisher=publisher or "Unknown publisher",
        published_at=_parse_published(published_text),
        retrieved_at=retrieved_at,
        excerpt=clean_excerpt or None,
        feed_id=feed_id,
    )


class NewsProviderError(RuntimeError):
    """Visible RSS provider or response failure."""

    def __init__(
        self,
        message: str,
        *,
        provider: str,
        feed_id: str,
        error_code: str,
        retryable: bool,
    ) -> None:
        super().__init__(message)
        self.provider = provider
        self.feed_id = feed_id
        self.error_code = error_code
        self.retryable = retryable


class RssNewsProvider:
    """Conservative RSS 2.0/Atom polling with bounded retries."""

    def __init__(
        self,
        *,
        client: httpx.Client | None = None,
        max_attempts: int = 3,
        retry_base_delay: float = 1.0,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1.")
        self._client = client or httpx.Client(timeout=httpx.Timeout(20.0))
        self._owns_client = client is None
        self._max_attempts = max_attempts
        self._retry_base_delay = retry_base_delay
        self._sleep = sleep

    def close(self) -> None:
        if self._owns_client:
            self._client.close()

    def fetch(
        self,
        *,
        feed_id: str,
        url: str,
        allowed_excerpt_chars: int = 500,
    ) -> list[NewsArticle]:
        for attempt in range(1, self._max_attempts + 1):
            try:
                response = self._client.get(url, follow_redirects=True)
            except httpx.TransportError as error:
                if attempt < self._max_attempts:
                    self._sleep(self._retry_base_delay * attempt)
                    continue
                raise NewsProviderError(
                    "RSS feed request failed after transient network errors.",
                    provider="rss",
                    feed_id=feed_id,
                    error_code="feed_network_error",
                    retryable=True,
                ) from error

            if response.status_code in {429} or 500 <= response.status_code < 600:
                if attempt < self._max_attempts:
                    self._sleep(self._retry_base_delay * attempt)
                    continue
                raise NewsProviderError(
                    f"RSS feed returned HTTP {response.status_code}.",
                    provider="rss",
                    feed_id=feed_id,
                    error_code="feed_http_error",
                    retryable=True,
                )
            if response.status_code >= 400:
                raise NewsProviderError(
                    f"RSS feed returned HTTP {response.status_code}.",
                    provider="rss",
                    feed_id=feed_id,
                    error_code="feed_http_error",
                    retryable=False,
                )
            return parse_feed_xml(
                response.content,
                feed_id=feed_id,
                retrieved_at=datetime.now(UTC),
                allowed_excerpt_chars=allowed_excerpt_chars,
            )
        raise RuntimeError("RSS retry loop exhausted unexpectedly.")


class NewsIngestionService:
    """Poll feeds and persist normalized articles through one repository boundary."""

    def __init__(
        self,
        repository: NewsRepositoryProtocol,
        provider: RssNewsProvider,
    ) -> None:
        self._repository = repository
        self._provider = provider

    def poll(
        self,
        feeds: Sequence[tuple[str, str]],
        *,
        allowed_excerpt_chars: int = 500,
    ) -> list[NewsFeedRun]:
        runs: list[NewsFeedRun] = []
        for feed_id, url in feeds:
            started_at = datetime.now(UTC)
            run_id = self._repository.start_feed_run(feed_id, url, started_at)
            try:
                articles = self._provider.fetch(
                    feed_id=feed_id,
                    url=url,
                    allowed_excerpt_chars=allowed_excerpt_chars,
                )
                persisted = 0
                canonical_added = 0
                duplicates = 0
                for article in articles:
                    added_canonical = self._repository.persist_article(article)
                    persisted += 1
                    canonical_added += int(added_canonical)
                    duplicates += int(not added_canonical)
                self._repository.complete_feed_run(
                    run_id,
                    articles_received=len(articles),
                    articles_persisted=persisted,
                    canonical_articles_added=canonical_added,
                    duplicates_collapsed=duplicates,
                )
                runs.append(
                    NewsFeedRun(
                        feed_id=feed_id,
                        status="succeeded",
                        started_at=started_at,
                        completed_at=datetime.now(UTC),
                        articles_received=len(articles),
                        articles_persisted=persisted,
                        canonical_articles_added=canonical_added,
                        duplicates_collapsed=duplicates,
                    )
                )
            except NewsProviderError as error:
                self._repository.fail_feed_run(
                    run_id,
                    error_code=error.error_code,
                    error_message=str(error),
                )
                runs.append(
                    NewsFeedRun(
                        feed_id=feed_id,
                        status="failed",
                        started_at=started_at,
                        completed_at=datetime.now(UTC),
                        error_code=error.error_code,
                        error_message=str(error),
                    )
                )
            except Exception as error:
                self._repository.fail_feed_run(
                    run_id,
                    error_code="unexpected_ingestion_error",
                    error_message=str(error),
                )
                runs.append(
                    NewsFeedRun(
                        feed_id=feed_id,
                        status="failed",
                        started_at=started_at,
                        completed_at=datetime.now(UTC),
                        error_code="unexpected_ingestion_error",
                        error_message=str(error),
                    )
                )
        return runs


def parse_feed_configuration(value: str) -> list[tuple[str, str]]:
    """Parse semicolon-separated ``feed-id=https://...`` configuration."""
    feeds: list[tuple[str, str]] = []
    seen: set[str] = set()
    for entry in value.split(";"):
        entry = entry.strip()
        if not entry:
            continue
        if "=" not in entry:
            raise ValueError("RSS feed entries must use feed-id=https://... format.")
        feed_id, url = entry.split("=", 1)
        feed_id = feed_id.strip()
        if not feed_id or feed_id in seen:
            raise ValueError("RSS feed IDs must be non-empty and unique.")
        url = url.strip()
        split = urlsplit(url)
        if split.scheme not in {"http", "https"} or not split.netloc:
            raise ValueError("RSS feed URLs must be absolute HTTP(S).")
        seen.add(feed_id)
        feeds.append((feed_id, url))
    return feeds
