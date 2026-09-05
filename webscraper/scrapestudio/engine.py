"""Abruf-Maschine: holt Seiten, folgt Links, hält sich an robots.txt.

Läuft in einem eigenen Thread, meldet Fortschritt über Rückrufe und lässt
sich jederzeit abbrechen. Die eigentliche Extraktion macht entweder
``extractors`` (kostenlos) oder das Agenten-Team (siehe ``agents``).
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from typing import Callable, Iterable
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

import requests
from bs4 import BeautifulSoup

from .models import PageResult, ScrapeOptions

ProgressFn = Callable[[str, dict], None]


@dataclass
class Fetched:
    """Rohe Antwort einer Seite, bevor extrahiert wird."""

    url: str
    html: str
    status: int
    elapsed: float
    depth: int
    error: str = ""

    @property
    def ok(self) -> bool:
        return not self.error and 200 <= self.status < 300


def normalise_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return ""
    if not urlparse(url).scheme:
        url = "https://" + url
    # Fragment abschneiden: #abschnitt ist dieselbe Seite
    return url.split("#", 1)[0].rstrip("/") or url


def page_title(html: str) -> str:
    try:
        node = BeautifulSoup(html, "lxml").find("title")
        return node.get_text(strip=True) if node else ""
    except Exception:
        return ""


class RobotsCache:
    """robots.txt je Domain einmal holen und merken."""

    def __init__(self, user_agent: str, timeout: int = 10) -> None:
        self.user_agent = user_agent
        self.timeout = timeout
        self._cache: dict[str, RobotFileParser | None] = {}
        self._lock = threading.Lock()

    def allowed(self, url: str) -> bool:
        parsed = urlparse(url)
        root = f"{parsed.scheme}://{parsed.netloc}"
        with self._lock:
            parser = self._cache.get(root, "missing")  # type: ignore[arg-type]
        if parser == "missing":
            parser = self._load(root)
            with self._lock:
                self._cache[root] = parser
        if parser is None:
            return True  # keine robots.txt erreichbar -> nicht blockieren
        try:
            return parser.can_fetch(self.user_agent, url)
        except Exception:
            return True

    def _load(self, root: str) -> RobotFileParser | None:
        try:
            response = requests.get(
                f"{root}/robots.txt",
                timeout=self.timeout,
                headers={"User-Agent": self.user_agent},
            )
            if response.status_code >= 400:
                return None
            parser = RobotFileParser()
            parser.parse(response.text.splitlines())
            return parser
        except requests.RequestException:
            return None


class Crawler:
    """Sammelt Seiten gemäss Optionen ein."""

    def __init__(self, options: ScrapeOptions, progress: ProgressFn | None = None) -> None:
        self.options = options
        self.progress = progress or (lambda event, data: None)
        self._cancel = threading.Event()
        self._session = requests.Session()
        self._session.headers.update({
            "User-Agent": options.user_agent,
            "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
        })
        self._robots = RobotsCache(options.user_agent, options.timeout)
        self._seen: set[str] = set()
        self._lock = threading.Lock()

    def cancel(self) -> None:
        self._cancel.set()

    @property
    def cancelled(self) -> bool:
        return self._cancel.is_set()

    # ------------------------------------------------------------------
    def fetch(self, url: str, depth: int = 0) -> Fetched:
        """Eine Seite holen, mit Wiederholungen bei Netzfehlern."""
        if self.options.respect_robots and not self._robots.allowed(url):
            return Fetched(url, "", 0, 0.0, depth, error="Von robots.txt untersagt")

        last_error = ""
        for attempt in range(max(1, self.options.retries + 1)):
            if self.cancelled:
                return Fetched(url, "", 0, 0.0, depth, error="Abgebrochen")
            started = time.time()
            try:
                response = self._session.get(
                    url,
                    timeout=self.options.timeout,
                    verify=self.options.verify_ssl,
                    allow_redirects=True,
                )
                elapsed = time.time() - started
                content_type = response.headers.get("Content-Type", "")
                if "html" not in content_type and "xml" not in content_type:
                    return Fetched(
                        url, "", response.status_code, elapsed, depth,
                        error=f"Kein HTML ({content_type or 'unbekannt'})",
                    )
                if response.status_code >= 400:
                    last_error = f"HTTP {response.status_code}"
                    # 4xx wiederholen bringt nichts, 5xx schon
                    if response.status_code < 500:
                        return Fetched(url, "", response.status_code, elapsed, depth,
                                       error=last_error)
                else:
                    response.encoding = response.encoding or response.apparent_encoding
                    return Fetched(url, response.text, response.status_code, elapsed, depth)
            except requests.RequestException as exc:
                last_error = f"{type(exc).__name__}: {exc}"

            if attempt < self.options.retries:
                time.sleep(min(2 ** attempt, 8))

        return Fetched(url, "", 0, 0.0, depth, error=last_error or "Abruf fehlgeschlagen")

    # ------------------------------------------------------------------
    def links_on(self, html: str, base_url: str) -> list[str]:
        """Folgbare Links einer Seite gemäss Filtern."""
        soup = BeautifulSoup(html, "lxml")
        base_host = urlparse(base_url).netloc
        found: list[str] = []
        for node in soup.find_all("a", href=True):
            href = node["href"].strip()
            if href.startswith(("mailto:", "tel:", "javascript:", "#")):
                continue
            absolute = normalise_url(urljoin(base_url, href))
            if not absolute.startswith(("http://", "https://")):
                continue
            if self.options.same_domain_only and urlparse(absolute).netloc != base_host:
                continue
            if self.options.url_contains and self.options.url_contains not in absolute:
                continue
            found.append(absolute)
        return list(dict.fromkeys(found))

    # ------------------------------------------------------------------
    def run(self) -> list[Fetched]:
        """Alle Seiten einsammeln (Breitensuche über die Tiefe)."""
        queue: list[tuple[str, int]] = []
        for raw in self.options.urls:
            url = normalise_url(raw)
            if url and url not in self._seen:
                self._seen.add(url)
                queue.append((url, 0))

        pages: list[Fetched] = []
        max_pages = max(1, self.options.max_pages)

        while queue and len(pages) < max_pages and not self.cancelled:
            batch = queue[: max(1, self.options.workers)]
            queue = queue[len(batch):]

            results = self._fetch_batch(batch)
            for fetched in results:
                if len(pages) >= max_pages:
                    break
                pages.append(fetched)
                self.progress("page", {
                    "url": fetched.url,
                    "status": fetched.status,
                    "error": fetched.error,
                    "done": len(pages),
                    "total": min(max_pages, len(pages) + len(queue)),
                })

                if (
                    self.options.follow_links
                    and fetched.ok
                    and fetched.depth < self.options.max_depth
                    and len(pages) + len(queue) < max_pages
                ):
                    for link in self.links_on(fetched.html, fetched.url):
                        with self._lock:
                            if link in self._seen:
                                continue
                            self._seen.add(link)
                        queue.append((link, fetched.depth + 1))
                        if len(pages) + len(queue) >= max_pages:
                            break

            if queue and self.options.delay > 0 and not self.cancelled:
                time.sleep(self.options.delay)

        return pages

    def _fetch_batch(self, batch: Iterable[tuple[str, int]]) -> list[Fetched]:
        """Eine Handvoll Seiten parallel holen, Reihenfolge bleibt stabil."""
        batch = list(batch)
        results: list[Fetched | None] = [None] * len(batch)
        threads: list[threading.Thread] = []

        def work(index: int, url: str, depth: int) -> None:
            results[index] = self.fetch(url, depth)

        for index, (url, depth) in enumerate(batch):
            thread = threading.Thread(target=work, args=(index, url, depth), daemon=True)
            thread.start()
            threads.append(thread)
        for thread in threads:
            thread.join()

        return [r for r in results if r is not None]


def to_page_result(fetched: Fetched, rows: list[dict] | None = None) -> PageResult:
    return PageResult(
        url=fetched.url,
        status=fetched.status,
        title=page_title(fetched.html) if fetched.html else "",
        depth=fetched.depth,
        elapsed=round(fetched.elapsed, 3),
        bytes=len(fetched.html.encode("utf-8", "ignore")) if fetched.html else 0,
        rows=rows or [],
        error=fetched.error,
    )
