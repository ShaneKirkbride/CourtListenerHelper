import types
import pytest
from unittest.mock import MagicMock

from CourtListenerHelper import sanitize_filename, ApiClient, CaseSearcher, CaseDownloader


def test_sanitize_filename_simple():
    assert sanitize_filename('simple-name') == 'simple-name'


def test_sanitize_filename_special_chars():
    name = 'Hello:Case/Name?'
    assert sanitize_filename(name) == 'Hello_Case_Name_'


def test_case_searcher_pagination():
    mock_client = MagicMock()
    first_resp = MagicMock()
    first_resp.json.return_value = {
        'results': [{'id': 1, 'url': '/case/1'}],
        'next': '/search/?page=2'
    }
    second_resp = MagicMock()
    second_resp.json.return_value = {
        'results': [{'id': 2, 'url': '/case/2'}],
        'next': None
    }
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
    second = MagicMock(status_code=200)
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
    mock_client.get.return_value = response
    downloader = CaseDownloader(mock_client)
    result = downloader.download('/case/1')
    assert result == {'foo': 'bar'}
    mock_client.get.assert_called_with('/case/1')

