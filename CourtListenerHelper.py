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
import requests
import time
import os
import logging
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
    """Uses search API to query cases by keyword with optional jurisdiction filter."""

    def __init__(self, client: ApiClient, page_size: int = 100):
        self.client = client
        self.page_size = page_size

    def search(
        self,
        keyword: str,
        jurisdictions: Optional[Union[str, Iterable[str]]] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> Generator[Dict, None, None]:
        path = "/search/"
        params = {
            "q": keyword,
            "type": "o",
            "page_size": self.page_size,
        }
        if jurisdictions:
            if isinstance(jurisdictions, str):
                params["case__court__jurisdictions"] = jurisdictions
            else:
                params["case__court__jurisdictions"] = ",".join(jurisdictions)
        if start_date and end_date:
            params["date_filed__range"] = f"{start_date},{end_date}"
        else:
            if start_date:
                params["date_filed__gte"] = start_date
            if end_date:
                params["date_filed__lte"] = end_date

        if start_date:
            params["date_filed_min"] = start_date
        if end_date:
            params["date_filed_max"] = end_date

        next_url = None
        while True:
            resp = self.client.get(next_url or path, params={} if next_url else params)
            resp.raise_for_status()
            js = resp.json()

            for result in js.get("results", []):
                text = f"{result.get('name','')} {result.get('snippet','')}".lower()
                if keyword_lc in text:
                    yield result

            next_url = js.get("next")
            if not next_url:
                break


class CaseDownloader:
    """ Downloads full case details and PDF given a case URL or ID. """

    def __init__(self, client: ApiClient):
        self.client = client

    def download(self, case_url: str) -> Dict:
        resp = self.client.get(case_url)
        resp.raise_for_status()
        case = resp.json()

        # Extract PDF bytes (same logic as before)
        pdf_bytes = self._extract_pdf(case)

        # Fetch opinions separately
        opinions = []
        try:
            opinions = self._fetch_opinions(case.get("cluster_id"))
        except HTTPError as e:
            self.client.logger.warning(
                f"Failed to fetch opinions for cluster {case.get('cluster_id')}: {e}"
            )
        
        return {"metadata": case, "pdf_bytes": pdf_bytes, "opinions": opinions}

    def _extract_pdf(self, case: Dict) -> Optional[bytes]:
        pdf_url = case.get("download_url") or case.get("download_pdf")
        if pdf_url:
            try:
                return self._download_pdf_bytes(pdf_url)
            except:
                pass

        # Fallback to docket entries:
        docket = case.get("docket")
        docket_id = docket.get("id") if isinstance(docket, dict) else str(docket).split("/")[-1]
        if docket_id:
            for ent in self._get_docket_entries(docket_id):
                file_url = ent.get("file", {}).get("url")
                if file_url:
                    try:
                        return self._download_pdf_bytes(file_url)
                    except:
                        continue
        return None

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
        opinions = resp.json().get("results", [])

        opinion_texts = []
        for op in opinions:
            # fields may include xml_harvard, html_lawbox, plain_text
            opinion_texts.append({
                "id": op.get("id"),
                "type": op.get("type"),
                "xml": op.get("xml_harvard"),
                "html": op.get("html_lawbox"),
                "plain_text": op.get("plain_text"),
                "download_url": op.get("download_url")
            })
        return opinion_texts

    def _get_docket_entries(self, docket_id: str) -> list:
        """Return list of docket entries by docket ID, not full URL."""
        path = f"/dockets/{docket_id}/entries/"
        resp = self.client.get(path)
        resp.raise_for_status()
        return resp.json().get("results", [])

    def _download_pdf_bytes(self, pdf_url: str) -> bytes:
        """Use client to fetch PDF bytes via GET."""
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
            help="Keywords to search for",
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
        main(
            args.keywords,
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
        # Iterate over all pages of search results
        for case_meta in searcher.search(keyword, jurisdictions=jurisdictions):
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
            pdf_url = full_case.get("download_url")
            if pdf_url:
                pdf_path = os.path.join(out_dir, f"{safe_name}_{case_id}.pdf")
                if not os.path.exists(pdf_path):
                    pdf_bytes = downloader.download_pdf(pdf_url)
                    with open(pdf_path, "wb") as pf:
                        pf.write(pdf_bytes)
            # Slight delay to avoid hitting API rate limits aggressively
            time.sleep(0.1)


if __name__ == "__main__":
    import sys
    if not TOKEN and not any(f in sys.argv for f in ("-h", "--help")):
        logger.error("\u274C Set COURTLISTENER_TOKEN env var.")
        sys.exit(1)
    cli = CommandLineInterface(ApiClient(API_BASE, TOKEN or ""))
    cli.run(sys.argv[1:])
