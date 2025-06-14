#!/usr/bin/env python3
"""
Download multiple court cases by keyword using CourtListener REST API (v4).
Design follows SOLID principles: each class has a single responsibility.
"""

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

    def get(
        self,
        path: str,
        params: Optional[Dict] = None,
        max_retries: int = 3,
    ) -> requests.Response:
        if params is None:
            params = {}
        url = f"{self.base_url}{path}"
        retries = 0
        while True:
            resp = requests.get(url, headers=self.headers, params=params)
            if resp.status_code == 429 and retries < max_retries:
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


class CaseSearcher:
    """ Uses search API to query cases by keyword """
    def __init__(self, client: ApiClient, page_size: int = 100):
        self.client = client
        self.page_size = page_size

    def search(self, keyword: str) -> Generator[Dict, None, None]:
        path = "/search/"
        params = {
            "q": keyword,
            "type": "o",  # case law (opinion)
            "page_size": self.page_size
        }
        next_url = None
        while True:
            if next_url:
                resp = self.client.get(next_url, params={})
            else:
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
        resp = self.client.get(case_url)
        return resp.json()


def sanitize_filename(name: str) -> str:
    """Return a filesystem-safe version of the given name."""
    return "".join(c if c.isalnum() or c in " _-" else "_" for c in name)


# === Example Use ===

def main(keywords: List[str], out_dir: str = "cases"):
    os.makedirs(out_dir, exist_ok=True)
    client = ApiClient(API_BASE, TOKEN)
    searcher = CaseSearcher(client)
    downloader = CaseDownloader(client)

    for keyword in keywords:
        logger.info("\U0001F50D Searching cases for '%s' …", keyword)
        for case_meta in searcher.search(keyword):
            case_id = case_meta["id"]
            case_url = case_meta["url"]
            case_name = case_meta.get("name", f"case_{case_id}")
            safe_name = sanitize_filename(case_name)
            filename = os.path.join(out_dir, f"{safe_name}_{case_id}.json")
            if os.path.exists(filename):
                logger.info("\u2705 Skipping existing %s", filename)
                continue
            logger.info("\u2B07\uFE0F  Downloading case '%s' …", case_name)
            full_case = downloader.download(case_url)
            with open(filename, "w", encoding="utf-8") as f:
                import json
                json.dump(full_case, f, indent=2)
            time.sleep(0.1)


if __name__ == "__main__":
    import sys
    if not TOKEN:
        logger.error("\u274C Set COURTLISTENER_TOKEN env var.")
        sys.exit(1)
    if len(sys.argv) < 2:
        logger.info("Usage: script.py keyword1 keyword2 …")
        sys.exit(1)
    main(sys.argv[1:])
