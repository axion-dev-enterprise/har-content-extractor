"""
Extractor — Executes the AI-generated extraction plan via HTTP requests.

Handles pagination, concurrent downloads, rate limiting, and asset downloading.
"""

from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import requests
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn

from ai_analyzer import ExtractionPlan, ExtractionStep

console = Console()

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
    "Accept": "application/json, text/html, */*",
    "Accept-Language": "pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7",
}


def _resolve_data_path(data: Any, path: str) -> Any:
    """
    Navigate a nested dict/list using a dot-separated path.

    Example: _resolve_data_path({"data": {"products": [...]}}, "data.products") => [...]
    """
    if not path:
        return data

    keys = path.split(".")
    current = data
    for key in keys:
        if isinstance(current, dict):
            current = current.get(key, current)
        elif isinstance(current, list) and key.isdigit():
            idx = int(key)
            if idx < len(current):
                current = current[idx]
            else:
                return current
        else:
            return current
    return current


def _filter_fields(items: list[dict], fields: list[str]) -> list[dict]:
    """If fields are specified, only keep those keys from each item."""
    if not fields:
        return items

    filtered = []
    for item in items:
        if isinstance(item, dict):
            row = {}
            for f in fields:
                # Support nested dot notation
                parts = f.split(".")
                val = item
                for p in parts:
                    if isinstance(val, dict):
                        val = val.get(p, "")
                    else:
                        val = ""
                        break
                row[f] = val
            filtered.append(row)
        else:
            filtered.append({"value": item})
    return filtered


def _execute_step(
    step: ExtractionStep,
    session: requests.Session,
    max_pages: int = 50,
    replay_headers: dict[str, str] | None = None,
) -> list[dict]:
    """Execute a single extraction step, handling pagination."""
    results: list[dict] = []

    headers = {**DEFAULT_HEADERS}
    if replay_headers:
        headers.update(replay_headers)
    if step.headers:
        headers.update(step.headers)

    pagination = step.pagination
    current_page = 0
    page_param_value = None

    if pagination:
        page_param_value = pagination.get("start", 1)
        page_step = pagination.get("step", 1)
        max_pages = min(max_pages, pagination.get("max", max_pages))

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task = progress.add_task(
            f"[cyan]{step.description[:60]}",
            total=max_pages if pagination else 1,
        )

        while current_page < (max_pages if pagination else 1):
            # Build URL and params
            url = step.url_template
            params = dict(step.params)

            if pagination and page_param_value is not None:
                param_name = pagination.get("param", "page")
                params[param_name] = page_param_value

            try:
                if step.method == "POST":
                    resp = session.post(url, headers=headers, json=step.body, params=params, timeout=30)
                else:
                    resp = session.get(url, headers=headers, params=params, timeout=30)

                resp.raise_for_status()

                # Parse response
                content_type = resp.headers.get("content-type", "")
                if "json" in content_type:
                    data = resp.json()
                elif "xml" in content_type:
                    # Store raw XML as a single entry
                    results.append({"_raw_xml": resp.text[:10000], "_url": resp.url})
                    current_page += 1
                    progress.update(task, advance=1)
                    continue
                else:
                    # HTML or other — store raw
                    results.append({"_raw_html": resp.text[:10000], "_url": resp.url})
                    current_page += 1
                    progress.update(task, advance=1)
                    continue

                # Navigate to data path
                items = _resolve_data_path(data, step.data_path)

                if isinstance(items, list):
                    filtered = _filter_fields(items, step.fields)
                    results.extend(filtered)

                    # Check if we got empty results (end of pagination)
                    if len(items) == 0:
                        console.print(f"  [dim]Empty page at {current_page + 1}, stopping.[/]")
                        break
                elif isinstance(items, dict):
                    filtered = _filter_fields([items], step.fields)
                    results.extend(filtered)
                else:
                    results.append({"value": items, "_url": resp.url})

            except requests.exceptions.HTTPError as e:
                console.print(f"  [red]HTTP Error: {e}[/]")
                if resp.status_code in (401, 403):
                    console.print("  [yellow]Authentication required. Use --replay-headers to include captured cookies/tokens.[/]")
                    break
                if resp.status_code == 429:
                    console.print("  [yellow]Rate limited. Waiting 5s...[/]")
                    time.sleep(5)
                    continue
            except requests.exceptions.RequestException as e:
                console.print(f"  [red]Request failed: {e}[/]")
                break

            current_page += 1
            progress.update(task, advance=1)

            # Update pagination value
            if pagination and page_param_value is not None:
                page_step = pagination.get("step", 1)
                page_param_value += page_step

            # Rate limiting between requests
            time.sleep(0.3)

    return results


def download_assets(
    urls: list[str],
    output_dir: str,
    concurrency: int = 3,
    replay_headers: dict[str, str] | None = None,
) -> list[str]:
    """
    Download a list of asset URLs (images, files) concurrently.

    Returns list of saved file paths.
    """
    out_path = Path(output_dir) / "downloads"
    out_path.mkdir(parents=True, exist_ok=True)

    headers = {**DEFAULT_HEADERS}
    if replay_headers:
        headers.update(replay_headers)

    saved: list[str] = []

    def _download(url: str) -> str | None:
        try:
            resp = requests.get(url, headers=headers, timeout=30, stream=True)
            resp.raise_for_status()

            # Derive filename from URL
            from urllib.parse import urlparse
            parsed = urlparse(url)
            filename = Path(parsed.path).name or "asset"
            if not Path(filename).suffix:
                ct = resp.headers.get("content-type", "")
                if "jpeg" in ct or "jpg" in ct:
                    filename += ".jpg"
                elif "png" in ct:
                    filename += ".png"
                elif "webp" in ct:
                    filename += ".webp"
                elif "gif" in ct:
                    filename += ".gif"

            # Avoid collisions
            dest = out_path / filename
            counter = 1
            while dest.exists():
                stem = Path(filename).stem
                ext = Path(filename).suffix
                dest = out_path / f"{stem}_{counter}{ext}"
                counter += 1

            with open(dest, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8192):
                    f.write(chunk)

            return str(dest)
        except Exception as e:
            console.print(f"  [red]Failed to download {url[:80]}: {e}[/]")
            return None

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TaskProgressColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("[cyan]Downloading assets", total=len(urls))

        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = {executor.submit(_download, url): url for url in urls}
            for future in as_completed(futures):
                result = future.result()
                if result:
                    saved.append(result)
                progress.update(task, advance=1)

    console.print(f"[green]Downloaded {len(saved)}/{len(urls)} assets to {out_path}[/]")
    return saved


def extract(
    plan: ExtractionPlan,
    output_dir: str = "output",
    max_pages: int = 50,
    concurrency: int = 3,
    replay_headers: dict[str, str] | None = None,
    download_assets_flag: bool = False,
) -> list[dict]:
    """
    Execute the full extraction plan.

    Args:
        plan: Extraction plan from the AI analyzer.
        output_dir: Directory for output files and downloads.
        max_pages: Max pages to fetch per paginated step.
        concurrency: Concurrent download threads.
        replay_headers: Headers captured from HAR to replay (cookies, auth).
        download_assets_flag: Whether to download referenced assets.

    Returns:
        List of extracted data records.
    """
    if not plan.steps:
        console.print("[yellow]No extraction steps in plan. Nothing to extract.[/]")
        return []

    session = requests.Session()
    all_results: list[dict] = []

    console.print(f"\n[bold blue]Executing {len(plan.steps)} extraction step(s)...[/]")

    for i, step in enumerate(plan.steps, 1):
        console.print(f"\n[bold]Step {i}/{len(plan.steps)}:[/] {step.description}")
        step_results = _execute_step(step, session, max_pages=max_pages, replay_headers=replay_headers)
        console.print(f"  [green]Got {len(step_results)} records[/]")
        all_results.extend(step_results)

    console.print(f"\n[bold green]Total records extracted: {len(all_results)}[/]")

    # Download assets if requested
    if download_assets_flag and all_results:
        asset_urls = []
        for record in all_results:
            for key, val in record.items():
                if isinstance(val, str) and (val.startswith("http://") or val.startswith("https://")):
                    asset_urls.append(val)

        if asset_urls:
            console.print(f"\n[bold]Found {len(asset_urls)} asset URLs to download[/]")
            download_assets(asset_urls, output_dir, concurrency=concurrency, replay_headers=replay_headers)

    # Save raw JSON results
    out_path = Path(output_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    raw_path = out_path / "raw_results.json"
    with open(raw_path, "w", encoding="utf-8") as f:
        json.dump(all_results, f, indent=2, ensure_ascii=False)
    console.print(f"[dim]Raw results saved to {raw_path}[/]")

    return all_results
