import subprocess, json, os

# Resolve repository root (4 levels up from this file)
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))
VENDOR = os.path.join(REPO_ROOT, 'vendor', 'web-scraper')
VENDOR = os.path.normpath(VENDOR)


def run_example_api_scraper(ids=[123], timeout=120):
    """Run the Node example in vendor/web-scraper/examples/api-scraper.js.

    Executes `node examples/api-scraper.js` with the vendor dir as cwd so Node
    resolves local modules correctly. Returns a dict with returncode, stdout, stderr.
    """
    js_rel = os.path.join('examples', 'api-scraper.js')
    try:
        p = subprocess.run(['node', js_rel], cwd=VENDOR, capture_output=True, text=True, timeout=timeout)
        return {'returncode': p.returncode, 'stdout': p.stdout, 'stderr': p.stderr}
    except subprocess.TimeoutExpired as e:
        return {'returncode': -1, 'stdout': '', 'stderr': 'timeout'}
    except FileNotFoundError as e:
        return {'returncode': -2, 'stdout': '', 'stderr': 'node-not-found'}


def run_cheerio_sitemap_example(timeout=120):
    """Run the Cheerio (HTTP-only) sitemap example as a lightweight fallback.

    Executes `node examples/sitemap-basic.js` in the vendor dir. This uses
    CheerioCrawler (HTTP requests + cheerio) and avoids Playwright/browser.
    """
    js_rel = os.path.join('examples', 'sitemap-basic.js')
    try:
        p = subprocess.run(['node', js_rel], cwd=VENDOR, capture_output=True, text=True, timeout=timeout)
        return {'returncode': p.returncode, 'stdout': p.stdout, 'stderr': p.stderr}
    except subprocess.TimeoutExpired:
        return {'returncode': -1, 'stdout': '', 'stderr': 'timeout'}
    except FileNotFoundError:
        return {'returncode': -2, 'stdout': '', 'stderr': 'node-not-found'}


if __name__ == '__main__':
    print(run_example_api_scraper())
