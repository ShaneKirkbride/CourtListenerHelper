# CourtListener Helper

CourtListener Helper is a Python package and command line tool for
downloading case law documents from the [CourtListener REST API](https://www.courtlistener.com/api).
It exposes a small, SOLID-compliant architecture consisting of a reusable
`ApiClient` class, search and download helpers, and both CLI and Tkinter GUI
front ends.

## Features

- Search the CourtListener API by keyword
- Download full case metadata in JSON format
- Download the associated opinion PDF when available
- Retrieve docket PDFs via the RECAP system
- Command line and graphical interfaces
- Lightweight API metrics (call count, bytes and elapsed time)
- 100% unit test coverage

## Installation

Ensure you have **Python 3.12+** and install the required dependency:

```bash
pip install requests
```

## Usage

### Command Line

Set your API token in the environment variable `COURTLISTENER_TOKEN` and run:

```bash
python CourtListenerHelper.py "keyword" -o output_dir
```

Multiple keywords may be provided, and the tool will create the output
directory if necessary.

### GUI

Launch the Tkinter GUI with:

```bash
python gui.py
```

Enter keywords separated by commas, choose an output folder and click **Start**.
A progress bar and log will show download status and API metrics.

## Testing

Run the unit test suite with:

```bash
pytest
```

All tests should pass without network access because requests are mocked.

## Project Structure

- `CourtListenerHelper.py` – core implementation with API client, searcher,
  downloader, RECAP helper and CLI classes
- `gui.py` – simple Tkinter GUI wrapper around the same components
- `tests/` – `pytest` unit tests

The code follows SOLID principles: each class has a clear single responsibility
and depends on abstractions rather than concrete implementations. Components can
be reused or extended independently.

## License

This project is released into the public domain.
