# Ideogram Bulk Image Downloader

Downloads all your generated images from your ideogram.ai account.

## ⚡ Quick Start (run on your own machine)

```bash
pip install playwright
playwright install chromium

# Option A: Use your existing Chrome login (close Chrome first!)
python3 download_local.py --chrome-profile

# Option B: Opens a browser for you to log in
python3 download_local.py --headed

# Option C: Pass your session cookie
python3 download_local.py -s "eyJhbGciOi..."
```

## How It Works

Cloudflare blocks API access from servers/scripts, so this tool launches a real browser that:

1. Opens ideogram.ai with your credentials
2. Navigates to your creations page
3. Intercepts the internal API calls the webapp makes
4. Scrolls to load ALL your images (handles infinite scroll)
5. Downloads each image at full resolution
6. Saves a `metadata.json` with prompts, settings, and other data

## Files

| File | Description |
|------|-------------|
| `download_local.py` | **Use this one** — browser-based, runs on your machine |
| `download.py` | Direct API version (only works if Cloudflare isn't blocking) |
| `download_browser.py` | Headless browser version (for servers, less reliable) |

## Requirements

- Python 3.8+
- `playwright` (`pip install playwright`)
- Chromium (`playwright install chromium`)
- For `--chrome-profile` mode: close Chrome before running

## Output

Images are saved to `./ideogram_images/` by default with filenames like:
```
0001_A_serene_landscape_with_mountains.png
0002_Logo_design_for_tech_company.png
```

A `metadata.json` file contains the full API data for each image (prompt, settings, etc.)
