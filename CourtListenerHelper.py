#!/usr/bin/env python3
"""CourtListener Helper.

This module provides utilities to search for cases on the CourtListener REST
API and download their full contents to a directory chosen by the user.  The
code is organised around small classes that each focus on a single
responsibility following the SOLID principles.  It downloads both the case
metadata and the PDF opinion when available.  The module can be used either
from the command line via :class:`CommandLineInterface` or programmatically via
the ``main`` function.
"""

import argparse
import json
import requests
import time
import os
import logging
from typing import Generator, Dict, Optional, Union, List
from typing import List, Dict, Generator, Optional, Iterable, Union
from requests.adapters import HTTPAdapter, Retry

API_BASE = "https://www.courtlistener.com/api/rest/v4"
TOKEN = os.getenv("COURTLISTENER_TOKEN")  # Set your API token in env.

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)


class ApiClient:
    """Handles HTTP communication with CourtListener API."""

    def __init__(self, base_url: str, token: str):
        self.base_url = base_url.rstrip("/")
        self.headers = {"Authorization": f"Token {token}"}

        # Initialize metrics storage
        self.metrics = {
            "call_count": 0,
            "total_bytes": 0,
            "total_time": 0.0,
        }

        # Configure session with retries for 5xx errors
        self.session = requests.Session()
        retries = Retry(
            total=5,
            backoff_factor=1.5,
            status_forcelist=[500, 502, 503, 504],
            allowed_methods=["GET", "POST"],
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retries)
        self.session.mount("https://", adapter)
        self.session.mount("http://", adapter)

    def _update_metrics(self, resp: requests.Response, elapsed: float) -> None:
        self.metrics["call_count"] += 1
        self.metrics["total_bytes"] += len(resp.content)
        self.metrics["total_time"] += elapsed

    def get(self, path, params=None):
        if params is None: params = {}
        url = path if path.startswith("http") else f"{self.base_url}{path}"
        start = time.time()
        resp = self.session.get(url, headers=self.headers, params=params, timeout=30)
        elapsed = time.time() - start
        self._update_metrics(resp, elapsed)
        if resp.status_code >= 500:
            resp.raise_for_status()
        return resp

    def post(
        self,
        path: str,
        data: Optional[Dict] = None,
    ) -> requests.Response:
        """Perform a POST request and record metrics."""
        if data is None:
            data = {}
        url = path if path.startswith("http") else f"{self.base_url}{path}"
        start = time.time()
        resp = requests.post(url, headers=self.headers, data=data)
        elapsed = time.time() - start
        self.metrics["call_count"] += 1
        self.metrics["total_bytes"] += len(resp.content)
        self.metrics["total_time"] += elapsed
        resp.raise_for_status()
        return resp

    def get_metrics(self) -> Dict[str, float]:
        """Return collected metrics."""
        return dict(self.metrics)


class CaseSearcher:
    """Uses search API to query cases by keyword with optional court/date filters."""

    def __init__(self, client: ApiClient, page_size: int = 100) -> None:
        self.client = client
        self.page_size = page_size

    def search(
        self,
        keyword: str,
        courts: Optional[Union[str, List[str]]] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> Generator[Dict, None, None]:
        """Yield search results for ``keyword`` with optional filters."""

        path = "/search/"
        params = {
            "q": keyword,
            "type": "o",
            "page_size": self.page_size,
        }

        if courts:
            params["court"] = (
                ",".join(courts) if isinstance(courts, (list, tuple)) else courts
            )
        if start_date:
            params["filed_after"] = start_date
        if end_date:
            params["filed_before"] = end_date

        next_url: Optional[str] = None

        while True:
            resp = self.client.get(next_url or path, params={} if next_url else params)
            resp.raise_for_status()
            js = resp.json()

            for result in js.get("results", []):
                yield result

            next_url = js.get("next")
            if not next_url:
                break


class CaseDownloader:
    """Downloads full opinion texts for a given case."""

    def __init__(self, client: ApiClient) -> None:
        self.client = client

    def download_opinions(self, case_meta: Dict) -> Dict:
        """Return full case metadata and associated opinion texts."""

        case_id = get_case_id(case_meta)
        case_url = get_case_url(case_meta)
        resp = self.client.get(case_url)
        full_meta = resp.json()

        cluster_id = full_meta.get("cluster_id")
        opinions = self._fetch_opinions(cluster_id)

        return {
            "case_id": case_id,
            "case_meta": full_meta,
            "opinions": opinions,
        }

    def _fetch_opinions(self, cluster_id: int) -> List[Dict]:
        """
        Return list of opinions with full text fields:
        xml_harvard, html_lawbox, plain_text.
        """
        if not cluster_id:
            return []

        # Search opinions for this cluster
        path = f"/opinions/"
        params = {"cluster": cluster_id}
        resp = self.client.get(path, params=params)
        resp.raise_for_status()
        opinions = []
        for op in resp.json().get("results", []):
            opinions.append({
                "id": op.get("id"),
                "type": op.get("type"),
                "plain_text": op.get("plain_text"),
                "html_lawbox": op.get("html_lawbox"),
                "xml_harvard": op.get("xml_harvard"),
                "download_url": op.get("download_url"),
            })
        return opinions

    def _get_docket_entries(self, docket_id: str) -> list:
        """Return list of docket entries by docket ID, not full URL."""
        # Method retained for backwards compatibility but no longer used.
        path = f"/dockets/{docket_id}/entries/"
        resp = self.client.get(path)
        resp.raise_for_status()
        return resp.json().get("results", [])

    def _download_pdf_bytes(self, pdf_url: str) -> bytes:
        """Use client to fetch PDF bytes via GET."""
        # Method retained for backwards compatibility but no longer used.
        resp = self.client.get(pdf_url, stream=True)
        resp.raise_for_status()
        return resp.content

class RecapDownloader:
    """Download docket PDFs via the RECAP fetch endpoint."""

    def __init__(self, client: ApiClient, pacer_user: str, pacer_pass: str):
        self.client = client
        self.pacer_user = pacer_user
        self.pacer_pass = pacer_pass

    def get_recap_entries(self, docket_id: int) -> List[Dict]:
        """Return docket entries that have a RECAP document."""
        resp = self.client.get(f"/dockets/{docket_id}/entries/")
        entries = resp.json().get("results", [])
        return [e for e in entries if e.get("recap_document")]

    def request_pdf(self, recap_doc_id: int) -> Dict:
        """Request the PDF for ``recap_doc_id`` via the fetch endpoint."""
        data = {
            "request_type": "2",
            "recap_document": str(recap_doc_id),
            "pacer_username": self.pacer_user,
            "pacer_password": self.pacer_pass,
        }
        resp = self.client.post("/recap-fetch/", data=data)
        return resp.json()

    def poll_entry(self, entry_id: int, interval: int = 5, timeout: int = 300) -> str:
        """Poll until the docket entry file URL is available."""
        elapsed = 0
        while elapsed < timeout:
            resp = self.client.get(f"/docket-entries/{entry_id}/")
            entry = resp.json()
            url = entry.get("file", {}).get("url")
            if url:
                return url
            time.sleep(interval)
            elapsed += interval
        raise TimeoutError("PDF not ready within timeout")

    def download_pdf(self, url: str) -> bytes:
        """Return the PDF bytes at ``url``."""
        resp = self.client.get(url)
        return resp.content

    def fetch_first_pdf(self, docket_id: int) -> bytes:
        """Fetch the first available RECAP PDF for the docket."""
        entries = self.get_recap_entries(docket_id)
        if not entries:
            raise ValueError("No RECAP documents found")
        entry = entries[0]
        self.request_pdf(entry["recap_document"])
        url = self.poll_entry(entry["id"])
        return self.download_pdf(url)


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
            help="Words forming the search phrase",
        )
        self.parser.add_argument(
            "-o",
            "--output",
            default="cases",
            help="Directory to store downloaded cases",
        )
        self.parser.add_argument(
            "-j",
            "--jurisdiction",
            nargs="+",
            help="One or more jurisdiction slugs to filter results",
        )

    def run(self, argv: Optional[List[str]] = None) -> None:
        """Parse ``argv`` and download cases using the provided client."""
        args = self.parser.parse_args(argv)
        searcher = CaseSearcher(self.client)
        downloader = CaseDownloader(self.client)
        phrase = " ".join(args.keywords)
        main(
            [phrase],
            args.output,
            searcher,
            downloader,
            jurisdictions=args.jurisdiction,
        )


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
    """Return the API URL for a case from metadata."""
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
    jurisdictions: Optional[Union[str, Iterable[str]]] = None,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
):
    """Download all cases matching ``keywords`` into ``out_dir``.

    Parameters
    ----------
    keywords:
        Search terms used to query the API.
    out_dir:
        Directory where case files will be written.
    searcher, downloader:
        Optional pre-configured helper instances.
    jurisdictions:
        One or more jurisdiction slugs to limit results.
    """
    os.makedirs(out_dir, exist_ok=True)
    if searcher is None or downloader is None:
        client = ApiClient(API_BASE, TOKEN)
        if searcher is None:
            searcher = CaseSearcher(client)
        if downloader is None:
            downloader = CaseDownloader(client)

    for keyword in keywords:
        logger.info("\U0001F50D Searching cases for '%s' …", keyword)
        for case_meta in searcher.search(
            keyword,
            courts=jurisdictions,
            start_date=start_date,
            end_date=end_date,
        ):
            case_id = get_case_id(case_meta)
            safe_name = sanitize_filename(case_meta.get("name", f"case_{case_id}"))
            out_file = os.path.join(out_dir, f"{safe_name}_{case_id}_opinions.json")

            if os.path.exists(out_file):
                logger.info("\u2705 Skipping existing %s", out_file)
                continue

            logger.info("\u2B07\uFE0F  Downloading case '%s' …", case_meta.get("name"))
            data = downloader.download_opinions(case_meta)
            with open(out_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)

            time.sleep(0.1)


if __name__ == "__main__":
    import sys
    if not TOKEN and not any(f in sys.argv for f in ("-h", "--help")):
        logger.error("\u274C Set COURTLISTENER_TOKEN env var.")
        sys.exit(1)
    cli = CommandLineInterface(ApiClient(API_BASE, TOKEN or ""))
    cli.run(sys.argv[1:])
