# GitBook to PDF - Web Frontend

A web application that converts GitBook documentation into downloadable PDF files. Powered by [gitbook2pdf](https://github.com/fuergaosi233/gitbook2pdf).

## Quick Start

```bash
# Clone with submodules
git clone --recurse-submodules https://github.com/navrasa/cl_gitbook2pdf.git
cd cl_gitbook2pdf

# Build and run with Docker
docker-compose up --build
```

Then open [http://localhost:8000](http://localhost:8000) in your browser.

## Usage

1. Paste a GitBook URL into the input field
2. Click **Convert**
3. Watch the progress log as pages are crawled
4. Click **Download PDF** when conversion completes

## Architecture

- **Backend:** FastAPI with SSE (Server-Sent Events) for real-time progress
- **Frontend:** Vanilla HTML/CSS/JS
- **PDF Engine:** WeasyPrint (via gitbook2pdf)
- **Deployment:** Docker (required for WeasyPrint system dependencies)

## Development (without Docker)

Requires system libraries for WeasyPrint. See [WeasyPrint docs](https://doc.courtbouillon.org/weasyprint/stable/first_steps.html).

```bash
pip install -r requirements.txt
export PYTHONPATH="$(pwd)/gitbook2pdf:$PYTHONPATH"
mkdir -p output
uvicorn app.main:app --reload --port 8000
```

## Limitations

- One conversion runs at a time (WeasyPrint is memory-intensive)
- Large GitBooks may take several minutes and use significant memory
- The upstream gitbook2pdf project is archived; some newer GitBook layouts may not be supported
