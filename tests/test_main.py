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
    downloader.download_opinions.side_effect = [
        {"case_id": 1},
        {"case_id": 2},
    ]
    out_dir = tmp_path / "cases"
    main(["foo"], str(out_dir), searcher, downloader)
    for cid, name in [(1, "Foo Case"), (2, "Bar Case")]:
        safe = sanitize_filename(name)
        path = out_dir / f"{safe}_{cid}_opinions.json"
        assert path.exists()
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            assert data == {"case_id": cid}
    assert downloader.download_opinions.call_count == 2


def test_main_handles_cluster_id(tmp_path):
    searcher = MagicMock()
    downloader = MagicMock()
    searcher.search.return_value = [
        {"cluster_id": 42, "url": "/case/42", "name": "Cluster Case"},
    ]
    downloader.download_opinions.return_value = {
        "case_id": 42,
        "cluster_id": 42,
    }
    out_dir = tmp_path / "cases"
    main(["foo"], str(out_dir), searcher, downloader)
    safe = sanitize_filename("Cluster Case")
    path = out_dir / f"{safe}_42_opinions.json"
    assert path.exists()
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
        assert data == {"case_id": 42, "cluster_id": 42}
    downloader.download_opinions.assert_called_once()


def test_cli_invokes_main(monkeypatch):
    called = {}
    def fake_main(keywords, output, searcher, downloader, jurisdictions=None, start_date=None, end_date=None):
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
    assert called['keywords'] == ['foo bar']
    assert called['output'] == 'dest'
    assert called['jurisdictions'] == ['colo', 'circtdco']
    assert all(called['types'])
