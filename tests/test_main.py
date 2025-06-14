import json
from unittest.mock import MagicMock
from CourtListenerHelper import main, CommandLineInterface, ApiClient, CaseSearcher, CaseDownloader, sanitize_filename
import os

def test_main_writes_files(tmp_path):
    searcher = MagicMock()
    downloader = MagicMock()
    searcher.search.return_value = [
        {"id": 1, "url": "/case/1", "name": "Foo Case"},
        {"id": 2, "url": "/case/2", "name": "Bar Case"},
    ]
    downloader.download.side_effect = [
        {"id": 1},
        {"id": 2},
    ]
    out_dir = tmp_path / "cases"
    main(["foo"], str(out_dir), searcher, downloader)
    for cid, name in [(1, "Foo Case"), (2, "Bar Case")]:
        safe = sanitize_filename(name)
        path = out_dir / f"{safe}_{cid}.json"
        assert path.exists()
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
            assert data == {"id": cid}


def test_cli_invokes_main(monkeypatch):
    called = {}
    def fake_main(keywords, output, searcher, downloader):
        called['keywords'] = keywords
        called['output'] = output
        called['types'] = (isinstance(searcher, CaseSearcher), isinstance(downloader, CaseDownloader))
    monkeypatch.setattr('CourtListenerHelper.main', fake_main)
    cli = CommandLineInterface(ApiClient('http://example.com', 't'))
    cli.run(['foo', 'bar', '-o', 'dest'])
    assert called['keywords'] == ['foo', 'bar']
    assert called['output'] == 'dest'
    assert all(called['types'])
