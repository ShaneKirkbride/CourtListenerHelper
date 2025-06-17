import json
from unittest.mock import MagicMock
from CourtListenerHelper import (
    main,
    CommandLineInterface,
    ApiClient,
    CaseSearcher,
    CaseDownloader,
    sanitize_filename,
)
import os

def test_main_writes_files(tmp_path):
    searcher = MagicMock()
    downloader = MagicMock()
    searcher.search.return_value = [
        {"id": 1, "url": "/case/1", "name": "Foo Case"},
        {"id": 2, "url": "/case/2", "name": "Bar Case"},
    ]
    downloader.download.side_effect = [
        {"id": 1, "download_url": "http://example.com/1.pdf"},
        {"id": 2, "download_url": "http://example.com/2.pdf"},
    ]
    downloader.download_pdf.return_value = b"pdf"
    out_dir = tmp_path / "cases"
    main(["foo"], str(out_dir), searcher, downloader)
    for cid, name in [(1, "Foo Case"), (2, "Bar Case")]:
        safe = sanitize_filename(name)
        path = out_dir / f"{safe}_{cid}.json"
        assert path.exists()
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            assert data == {"id": cid, "download_url": f"http://example.com/{cid}.pdf"}
        pdf = out_dir / f"{safe}_{cid}.pdf"
        assert pdf.exists()
    assert downloader.download_pdf.call_count == 2


def test_main_handles_cluster_id(tmp_path):
    searcher = MagicMock()
    downloader = MagicMock()
    searcher.search.return_value = [
        {"cluster_id": 42, "url": "/case/42", "name": "Cluster Case"},
    ]
    downloader.download.return_value = {"cluster_id": 42, "download_url": "http://example.com/42.pdf"}
    downloader.download_pdf.return_value = b"pdf"
    out_dir = tmp_path / "cases"
    main(["foo"], str(out_dir), searcher, downloader)
    safe = sanitize_filename("Cluster Case")
    path = out_dir / f"{safe}_42.json"
    assert path.exists()
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
        assert data == {"cluster_id": 42, "download_url": "http://example.com/42.pdf"}
    pdf = out_dir / f"{safe}_42.pdf"
    assert pdf.exists()
    downloader.download_pdf.assert_called_once()


def test_cli_invokes_main(monkeypatch):
    called = {}
    def fake_main(keywords, output, searcher, downloader, jurisdictions=None):
        called['keywords'] = keywords
        called['output'] = output
        called['jurisdictions'] = jurisdictions
        called['types'] = (
            isinstance(searcher, CaseSearcher),
            isinstance(downloader, CaseDownloader),
        )
    monkeypatch.setattr('CourtListenerHelper.main', fake_main)
    cli = CommandLineInterface(ApiClient('http://example.com', 't'))
    cli.run(['foo', 'bar', '-o', 'dest', '-j', 'colo', 'circtdco'])
    assert called['keywords'] == ['foo', 'bar']
    assert called['output'] == 'dest'
    assert called['jurisdictions'] == ['colo', 'circtdco']
    assert all(called['types'])
