"""
HAR Parser — Parses HAR (HTTP Archive) files and builds a structured site profile.

Analyzes all captured network requests to identify:
- Domains and subdomains
- API endpoints and response structures
- CDN patterns (CloudFront, Akamai, Cloudflare, imgix, etc.)
- Content directories (images, scripts, stylesheets, fonts)
- Pagination patterns
- Authentication headers
"""

from __future__ import annotations

import json
import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, parse_qs

from rich.console import Console
from rich.table import Table

console = Console()

# Known CDN hostname patterns
CDN_PATTERNS: list[re.Pattern] = [
    re.compile(r"cloudfront\.net", re.I),
    re.compile(r"akamai(hd|edge)?\.net", re.I),
    re.compile(r"cdn\.shopify\.com", re.I),
    re.compile(r"fastly\.net", re.I),
    re.compile(r"imgix\.net", re.I),
    re.compile(r"cloudflare", re.I),
    re.compile(r"stackpath", re.I),
    re.compile(r"jsdelivr\.net", re.I),
    re.compile(r"unpkg\.com", re.I),
    re.compile(r"b-cdn\.net", re.I),   # BunnyCDN
    re.compile(r"azureedge\.net", re.I),
    re.compile(r"googleapis\.com", re.I),
    re.compile(r"gstatic\.com", re.I),
    re.compile(r"twimg\.com", re.I),
    re.compile(r"fbcdn\.net", re.I),
    re.compile(r"cdn\.", re.I),
]

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".avif", ".svg", ".ico", ".bmp", ".tiff"}
FONT_EXTENSIONS = {".woff", ".woff2", ".ttf", ".otf", ".eot"}
SCRIPT_EXTENSIONS = {".js", ".mjs", ".jsx", ".ts", ".tsx"}
STYLE_EXTENSIONS = {".css", ".scss", ".less"}
DATA_EXTENSIONS = {".json", ".xml", ".csv", ".graphql"}

PAGINATION_PARAMS = {"page", "p", "pg", "offset", "skip", "cursor", "after", "before", "start", "limit", "per_page", "pagesize", "page_size"}


@dataclass
class Endpoint:
    """Represents a discovered API endpoint."""
    method: str
    url: str
    path: str
    query_params: dict[str, list[str]]
    request_headers: dict[str, str]
    response_status: int
    response_content_type: str
    response_size: int
    response_body_preview: str = ""   # first 2000 chars


@dataclass
class SiteProfile:
    """Structured profile of a website derived from HAR analysis."""
    source_file: str = ""
    total_requests: int = 0
    domains: list[str] = field(default_factory=list)
    primary_domain: str = ""
    cdn_domains: list[str] = field(default_factory=list)
    api_endpoints: list[Endpoint] = field(default_factory=list)
    image_urls: list[str] = field(default_factory=list)
    font_urls: list[str] = field(default_factory=list)
    script_urls: list[str] = field(default_factory=list)
    style_urls: list[str] = field(default_factory=list)
    data_urls: list[str] = field(default_factory=list)
    content_types: dict[str, int] = field(default_factory=dict)
    pagination_patterns: list[dict[str, Any]] = field(default_factory=list)
    request_headers_sample: dict[str, str] = field(default_factory=dict)
    site_type: str = ""  # SPA, SSR, API-driven, static

    def to_dict(self) -> dict:
        """Serialize to a plain dict for AI consumption."""
        return {
            "source_file": self.source_file,
            "total_requests": self.total_requests,
            "domains": self.domains,
            "primary_domain": self.primary_domain,
            "cdn_domains": self.cdn_domains,
            "api_endpoints": [
                {
                    "method": ep.method,
                    "path": ep.path,
                    "query_params": ep.query_params,
                    "response_status": ep.response_status,
                    "response_content_type": ep.response_content_type,
                    "response_size": ep.response_size,
                    "response_body_preview": ep.response_body_preview[:500],
                }
                for ep in self.api_endpoints[:60]  # cap for token budget
            ],
            "image_urls_sample": self.image_urls[:30],
            "image_urls_count": len(self.image_urls),
            "content_types": self.content_types,
            "pagination_patterns": self.pagination_patterns,
            "request_headers_sample": self.request_headers_sample,
            "site_type": self.site_type,
        }


def _classify_url(url: str) -> str | None:
    """Classify a URL by its file extension."""
    parsed = urlparse(url)
    path = parsed.path.lower()
    ext = Path(path).suffix
    if ext in IMAGE_EXTENSIONS:
        return "image"
    if ext in FONT_EXTENSIONS:
        return "font"
    if ext in SCRIPT_EXTENSIONS:
        return "script"
    if ext in STYLE_EXTENSIONS:
        return "style"
    if ext in DATA_EXTENSIONS:
        return "data"
    return None


def _is_cdn(hostname: str) -> bool:
    """Check if hostname matches known CDN patterns."""
    return any(pat.search(hostname) for pat in CDN_PATTERNS)


def _detect_pagination(entries: list[dict]) -> list[dict[str, Any]]:
    """Detect pagination patterns from query parameters across entries."""
    patterns: list[dict[str, Any]] = []
    param_values: dict[str, list[str]] = defaultdict(list)

    for entry in entries:
        parsed = urlparse(entry.get("url", ""))
        qs = parse_qs(parsed.query)
        for param_name in PAGINATION_PARAMS:
            if param_name in qs:
                param_values[param_name].extend(qs[param_name])

    for param, values in param_values.items():
        if len(values) >= 2:
            try:
                nums = sorted(set(int(v) for v in values if v.isdigit()))
                if len(nums) >= 2:
                    step = nums[1] - nums[0]
                    patterns.append({
                        "param": param,
                        "values_seen": nums,
                        "step": step,
                        "type": "offset" if step > 1 else "page",
                    })
            except (ValueError, IndexError):
                patterns.append({
                    "param": param,
                    "values_seen": values[:10],
                    "type": "cursor",
                })

    return patterns


def _detect_site_type(entries: list[dict], domains: list[str]) -> str:
    """Heuristic detection of site architecture type."""
    content_types = Counter()
    has_html = False
    api_json_count = 0

    for entry in entries:
        ct = entry.get("response_content_type", "")
        content_types[ct] += 1
        if "html" in ct:
            has_html = True
        if "json" in ct or "graphql" in ct.lower():
            api_json_count += 1

    js_count = sum(1 for e in entries if _classify_url(e.get("url", "")) == "script")

    if api_json_count > len(entries) * 0.3 and js_count > 10:
        return "SPA (Single Page Application) — API-driven frontend"
    if has_html and api_json_count < 5:
        return "SSR (Server-Side Rendered) — Traditional multi-page"
    if api_json_count > len(entries) * 0.5:
        return "API-driven — Primarily data endpoints"
    if not has_html and js_count < 3:
        return "Static — Minimal dynamic content"
    return "Hybrid — Mix of SSR and API calls"


def _extract_response_preview(entry_response: dict) -> str:
    """Extract a preview of the response body text."""
    content = entry_response.get("content", {})
    text = content.get("text", "")
    if not text:
        return ""
    # Truncate
    return text[:2000]


def parse_har(filepath: str) -> SiteProfile:
    """
    Parse a HAR file and return a structured SiteProfile.

    Args:
        filepath: Path to the .har file.

    Returns:
        SiteProfile with all discovered information about the site.
    """
    path = Path(filepath)
    if not path.exists():
        raise FileNotFoundError(f"HAR file not found: {filepath}")

    console.print(f"[bold blue]Loading HAR file:[/] {path.name}")

    with open(path, "r", encoding="utf-8", errors="replace") as f:
        har_data = json.load(f)

    log = har_data.get("log", {})
    entries = log.get("entries", [])

    if not entries:
        raise ValueError("HAR file contains no entries.")

    console.print(f"[green]Found {len(entries)} requests[/]")

    profile = SiteProfile(source_file=str(path), total_requests=len(entries))

    # --- Collect data from each entry ---
    domain_counter: Counter = Counter()
    content_type_counter: Counter = Counter()
    all_entries_simplified: list[dict] = []
    first_headers_captured = False

    for entry in entries:
        request = entry.get("request", {})
        response = entry.get("response", {})

        method = request.get("method", "GET").upper()
        url = request.get("url", "")
        parsed = urlparse(url)
        hostname = parsed.hostname or ""
        path_str = parsed.path

        domain_counter[hostname] += 1

        # Response info
        status = response.get("status", 0)
        resp_headers = {h["name"].lower(): h["value"] for h in response.get("headers", [])}
        content_type = resp_headers.get("content-type", "")
        content_size = response.get("bodySize", 0)
        if content_size < 0:
            content_size = response.get("content", {}).get("size", 0)

        base_ct = content_type.split(";")[0].strip() if content_type else "unknown"
        content_type_counter[base_ct] += 1

        # Classify by extension
        url_type = _classify_url(url)
        if url_type == "image":
            profile.image_urls.append(url)
        elif url_type == "font":
            profile.font_urls.append(url)
        elif url_type == "script":
            profile.script_urls.append(url)
        elif url_type == "style":
            profile.style_urls.append(url)
        elif url_type == "data":
            profile.data_urls.append(url)

        # Also classify by content-type for URLs without extension
        if url_type is None:
            if "image" in base_ct:
                profile.image_urls.append(url)
            elif "json" in base_ct or "xml" in base_ct:
                profile.data_urls.append(url)

        # CDN detection
        if _is_cdn(hostname) and hostname not in profile.cdn_domains:
            profile.cdn_domains.append(hostname)

        # API endpoints: JSON/XML responses or data URLs
        if ("json" in base_ct or "xml" in base_ct or "graphql" in base_ct.lower()) and status < 400:
            qs = parse_qs(parsed.query)
            req_headers = {h["name"]: h["value"] for h in request.get("headers", [])}
            preview = _extract_response_preview(response)
            profile.api_endpoints.append(Endpoint(
                method=method,
                url=url,
                path=path_str,
                query_params=qs,
                request_headers=req_headers,
                response_status=status,
                response_content_type=base_ct,
                response_size=content_size,
                response_body_preview=preview,
            ))

        # Capture first set of request headers as sample
        if not first_headers_captured and hostname and method == "GET":
            req_headers = {h["name"]: h["value"] for h in request.get("headers", [])}
            profile.request_headers_sample = {
                k: v for k, v in req_headers.items()
                if k.lower() in {"user-agent", "accept", "accept-language", "cookie", "authorization", "referer", "x-requested-with"}
            }
            first_headers_captured = True

        all_entries_simplified.append({
            "url": url,
            "method": method,
            "status": status,
            "response_content_type": base_ct,
        })

    # --- Assemble profile ---
    sorted_domains = [d for d, _ in domain_counter.most_common()]
    profile.domains = sorted_domains
    profile.primary_domain = sorted_domains[0] if sorted_domains else ""
    profile.content_types = dict(content_type_counter.most_common())
    profile.pagination_patterns = _detect_pagination(all_entries_simplified)
    profile.site_type = _detect_site_type(all_entries_simplified, sorted_domains)

    # Deduplicate
    profile.image_urls = list(dict.fromkeys(profile.image_urls))
    profile.cdn_domains = list(dict.fromkeys(profile.cdn_domains))

    return profile


def print_profile(profile: SiteProfile) -> None:
    """Pretty-print a SiteProfile to the console."""
    console.print()
    console.print("[bold underline]Site Profile[/]")
    console.print(f"  Source: [dim]{profile.source_file}[/]")
    console.print(f"  Total Requests: [cyan]{profile.total_requests}[/]")
    console.print(f"  Primary Domain: [green]{profile.primary_domain}[/]")
    console.print(f"  Site Type: [yellow]{profile.site_type}[/]")
    console.print()

    # Domains table
    table = Table(title="Domains", show_lines=False)
    table.add_column("Domain", style="cyan")
    table.add_column("Requests", justify="right")
    domain_counts = Counter()
    for d in profile.domains:
        domain_counts[d] = 0
    # recount from content
    for d in profile.domains[:15]:
        table.add_row(d, "")
    console.print(table)

    # Content types
    ct_table = Table(title="Content Types", show_lines=False)
    ct_table.add_column("Type", style="magenta")
    ct_table.add_column("Count", justify="right")
    for ct, count in list(profile.content_types.items())[:15]:
        ct_table.add_row(ct, str(count))
    console.print(ct_table)

    # API Endpoints
    if profile.api_endpoints:
        api_table = Table(title=f"API Endpoints ({len(profile.api_endpoints)} found)", show_lines=False)
        api_table.add_column("Method", style="bold")
        api_table.add_column("Path", style="cyan", max_width=80)
        api_table.add_column("Status", justify="right")
        api_table.add_column("Type")
        for ep in profile.api_endpoints[:25]:
            api_table.add_row(ep.method, ep.path, str(ep.response_status), ep.response_content_type)
        console.print(api_table)

    # CDN
    if profile.cdn_domains:
        console.print(f"\n[bold]CDN Domains:[/] {', '.join(profile.cdn_domains)}")

    # Images
    console.print(f"\n[bold]Images found:[/] {len(profile.image_urls)}")
    for url in profile.image_urls[:5]:
        console.print(f"  [dim]{url[:120]}[/]")

    # Pagination
    if profile.pagination_patterns:
        console.print("\n[bold]Pagination Patterns:[/]")
        for pat in profile.pagination_patterns:
            console.print(f"  param=[cyan]{pat['param']}[/]  type={pat['type']}  values={pat.get('values_seen', [])[:5]}")

    console.print()
