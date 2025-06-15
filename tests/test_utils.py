import types
import pytest
from unittest.mock import MagicMock

from CourtListenerHelper import (
    sanitize_filename,
    ApiClient,
    CaseSearcher,
    CaseDownloader,
    get_case_id,
    get_case_url,
    API_BASE,
)


def test_sanitize_filename_simple():
    assert sanitize_filename('simple-name') == 'simple-name'


def test_sanitize_filename_special_chars():
    name = 'Hello:Case/Name?'
    assert sanitize_filename(name) == 'Hello_Case_Name_'


def test_sanitize_filename_with_spaces():
    name = 'A Case Name'
    assert sanitize_filename(name) == 'A Case Name'


def test_case_searcher_pagination():
    mock_client = MagicMock()
    first_resp = MagicMock()
    first_resp.json.return_value = {
        'results': [{'id': 1, 'url': '/case/1'}],
        'next': '/search/?page=2'
    }
    first_resp.content = b'{}'
    second_resp = MagicMock()
    second_resp.json.return_value = {
        'results': [{'id': 2, 'url': '/case/2'}],
        'next': None
    }
    second_resp.content = b'{}'
    mock_client.get.side_effect = [first_resp, second_resp]
    searcher = CaseSearcher(mock_client)
    results = list(searcher.search('keyword'))
    assert results == [
        {'id': 1, 'url': '/case/1'},
        {'id': 2, 'url': '/case/2'},
    ]
    assert mock_client.get.call_count == 2


def test_api_client_retry(monkeypatch):
    responses = []
    first = MagicMock(status_code=429, headers={'Retry-After': '0'})
    first.content = b''
    second = MagicMock(status_code=200)
    second.content = b''
    responses.extend([first, second])

    def fake_get(url, headers=None, params=None):
        return responses.pop(0)

    import requests
    monkeypatch.setattr(requests, 'get', fake_get)

    client = ApiClient('http://example.com', 't')
    resp = client.get('/path')
    assert resp.status_code == 200
    assert len(responses) == 0


def test_case_downloader_download():
    mock_client = MagicMock()
    response = MagicMock()
    response.json.return_value = {'foo': 'bar'}
    response.content = b'{}'
    mock_client.get.return_value = response
    downloader = CaseDownloader(mock_client)
    result = downloader.download('/case/1')
    assert result == {'foo': 'bar'}
    mock_client.get.assert_called_with('/case/1')


def test_get_case_id_variants():
    meta = {'id': 1, 'cluster_id': 2, 'docket_id': 3}
    assert get_case_id(meta) == '1'
    meta = {'cluster_id': 2, 'docket_id': 3}
    assert get_case_id(meta) == '2'
    meta = {'docket_id': 3}
    assert get_case_id(meta) == '3'


def test_get_case_url_variants():
    assert get_case_url({'url': '/case/1'}) == '/case/1'
    assert get_case_url({'resource_uri': '/case/2'}) == '/case/2'
    expected = f"{API_BASE}/case/3"
    assert get_case_url({'absolute_url': '/case/3'}) == expected
    with pytest.raises(KeyError):
        get_case_url({})


def test_gui_download_cases_handles_cluster_id(tmp_path):
    """GuiApplication should fall back to alternate IDs when 'id' is missing."""
    from gui import GuiApplication

    dummy = types.SimpleNamespace()
    dummy.client = MagicMock()
    dummy.client.get_metrics.return_value = {
        'call_count': 1,
        'total_bytes': 1,
        'total_time': 0,
    }
    dummy.searcher = MagicMock()
    dummy.downloader = MagicMock()
    dummy.progress = types.SimpleNamespace(step=lambda n: None)
    dummy.start_button = types.SimpleNamespace(config=lambda **kw: None)
    dummy.log_messages = []

    def log(msg):
        dummy.log_messages.append(msg)

    dummy.log_message = log

    dummy.searcher.search.return_value = [
        {"cluster_id": 99, "url": "/case/99", "name": "Cluster Case"}
    ]
    dummy.downloader.download.return_value = {"cluster_id": 99}

    out_dir = tmp_path / "cases"
    out_dir.mkdir()
    GuiApplication.download_cases(dummy, ["kw"], str(out_dir))

    expected = out_dir / "Cluster Case_99.json"
    assert expected.exists()

