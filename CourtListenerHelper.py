#!/usr/bin/env python3
"""CourtListener Helper.

This module provides utilities to search for cases on the CourtListener REST
API and download their full contents to a directory chosen by the user.  The
code is organised around small classes that each focus on a single
responsibility following the SOLID principles.  It can be used either from the
command line via :class:`CommandLineInterface` or programmatically via the
``main`` function.
"""

import argparse
import requests
import time
import os
import logging
from typing import List, Dict, Generator, Optional

API_BASE = "https://www.courtlistener.com/api/rest/v4"
TOKEN = os.getenv("COURTLISTENER_TOKEN")  # Set your API token in env.

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


class ApiClient:
    """Handles HTTP communication with CourtListener API."""

    def __init__(self, base_url: str, token: str):
        self.base_url = base_url.rstrip("/")
        self.headers = {
            "Authorization": f"Token {token}"
        }
        self.metrics = {
            "call_count": 0,
            "total_bytes": 0,
            "total_time": 0.0,
        }

    def get(
        self,
        path: str,
        params: Optional[Dict] = None,
        max_retries: int = 3,
    ) -> requests.Response:
        """Perform a GET request with basic retry and metric collection."""
        if params is None:
            params = {}
        if path.startswith("http"):
            url = path
        else:
            url = f"{self.base_url}{path}"
        retries = 0
        while True:
            # Measure duration so we can record API timing metrics
            start = time.time()
            resp = requests.get(url, headers=self.headers, params=params)
            elapsed = time.time() - start
            self.metrics["call_count"] += 1
            self.metrics["total_bytes"] += len(resp.content)
            self.metrics["total_time"] += elapsed
            if resp.status_code == 429 and retries < max_retries:
                # Respect server rate limiting and retry after the suggested delay
                wait = int(resp.headers.get("Retry-After", 60))
                logger.warning(
                    "Rate limited, retrying after %s seconds...", wait
                )
                time.sleep(wait)
                retries += 1
                continue
            break
        resp.raise_for_status()
        return resp

    def get_metrics(self) -> Dict[str, float]:
        """Return collected metrics."""
        return dict(self.metrics)


class CaseSearcher:
    """ Uses search API to query cases by keyword """
    def __init__(self, client: ApiClient, page_size: int = 100):
        self.client = client
        self.page_size = page_size

    def search(self, keyword: str) -> Generator[Dict, None, None]:
        """Yield search results for ``keyword`` one page at a time."""
        path = "/search/"
        params = {
            "q": keyword,
            "type": "o",  # case law (opinion)
            "page_size": self.page_size
        }
        next_url = None
        while True:
            if next_url:
                # Follow pagination links returned by the API
                resp = self.client.get(next_url, params={})
            else:
                # First page of results
                resp = self.client.get(path, params=params)
            js = resp.json()
            for result in js.get("results", []):
                yield result
            next_url = js.get("next")
            if not next_url:
                break


class CaseDownloader:
    """ Downloads full case details given case IDs """
    def __init__(self, client: ApiClient):
        self.client = client

    def download(self, case_url: str) -> Dict:
        """Return the JSON for a single case from its API URL."""
        resp = self.client.get(case_url)
        return resp.json()


class CommandLineInterface:
    """Handle command-line argument parsing and app execution."""

    def __init__(self, client: ApiClient):
        self.client = client
        self.parser = argparse.ArgumentParser(
            description="Download cases from CourtListener by keyword"
        )
        self.parser.add_argument(
            "keywords",
            nargs="+",
            help="Keywords to search for",
        )
        self.parser.add_argument(
            "-o",
            "--output",
            default="cases",
            help="Directory to store downloaded cases",
        )

    def run(self, argv: Optional[List[str]] = None) -> None:
        """Parse ``argv`` and download cases using the provided client."""
        args = self.parser.parse_args(argv)
        searcher = CaseSearcher(self.client)
        downloader = CaseDownloader(self.client)
        main(args.keywords, args.output, searcher, downloader)


def get_case_id(meta: Dict) -> str:
    """Return a stable identifier from case metadata.

    The CourtListener search API may provide different identifier fields. This
    helper checks common keys in priority order and returns the first one
    found. A ``KeyError`` is raised if no suitable identifier exists.
    """
    for key in ("id", "cluster_id", "docket_id"):
        if key in meta:
            return str(meta[key])
    raise KeyError("No case identifier found in metadata")


def get_case_url(meta: Dict) -> str:
    """Return the API URL for a case from metadata.

    The CourtListener search API historically exposed the key ``url`` for
    fetching full case details.  Some endpoints instead provide
    ``absolute_url`` or ``resource_uri``.  This helper normalises those
    variations so callers don't need to know the exact field name.
    """
    if "url" in meta:
        return meta["url"]
    if "resource_uri" in meta:
        return meta["resource_uri"]
    if "cluster_id" in meta:
        return f"/clusters/{meta['cluster_id']}/"
    if "absolute_url" in meta:
        url = meta["absolute_url"]
        if url.startswith("/api/"):
            return url
        if url.startswith("http") and "/api/" in url:
            return url
    raise KeyError("No case URL found in metadata")


def sanitize_filename(name: str) -> str:
    """Return a filesystem-safe version of ``name`` suitable for saving files."""
    return "".join(c if c.isalnum() or c in " _-" else "_" for c in name)


# === Example Use ===

def main(
    keywords: List[str],
    out_dir: str = "cases",
    searcher: Optional[CaseSearcher] = None,
    downloader: Optional[CaseDownloader] = None,
):
    """Download all cases matching ``keywords`` into ``out_dir``."""
    os.makedirs(out_dir, exist_ok=True)
    if searcher is None or downloader is None:
        client = ApiClient(API_BASE, TOKEN)
        if searcher is None:
            searcher = CaseSearcher(client)
        if downloader is None:
            downloader = CaseDownloader(client)

    for keyword in keywords:
        logger.info("\U0001F50D Searching cases for '%s' …", keyword)
        # Iterate over all pages of search results
        for case_meta in searcher.search(keyword):
            case_id = get_case_id(case_meta)
            case_url = get_case_url(case_meta)
            case_name = case_meta.get("name", f"case_{case_id}")
            safe_name = sanitize_filename(case_name)
            filename = os.path.join(out_dir, f"{safe_name}_{case_id}.json")
            if os.path.exists(filename):
                # Avoid re-downloading cases we already saved
                logger.info("\u2705 Skipping existing %s", filename)
                continue
            logger.info("\u2B07\uFE0F  Downloading case '%s' …", case_name)
            full_case = downloader.download(case_url)
            with open(filename, "w", encoding="utf-8") as f:
                import json
                json.dump(full_case, f, indent=2)
            # Slight delay to avoid hitting API rate limits aggressively
            time.sleep(0.1)


if __name__ == "__main__":
    import sys
    if not TOKEN and not any(f in sys.argv for f in ("-h", "--help")):
        logger.error("\u274C Set COURTLISTENER_TOKEN env var.")
        sys.exit(1)
    cli = CommandLineInterface(ApiClient(API_BASE, TOKEN or ""))
    cli.run(sys.argv[1:])
