import subprocess, json, os

# Resolve repository root (4 levels up from this file)
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', '..', '..'))
VENDOR = os.path.join(REPO_ROOT, 'vendor', 'web-scraper')
VENDOR = os.path.normpath(VENDOR)


def run_example_api_scraper(ids=[123]):
    """Run the Node example in vendor/web-scraper/examples.

    Executes `node examples/api-scraper.js` with the vendor dir as cwd so Node
    resolves local modules correctly. Returns a dict with returncode, stdout, stderr.
    """
    js_rel = os.path.join('examples', 'api-scraper.js')
    try:
        p = subprocess.run(['node', js_rel], cwd=VENDOR, capture_output=True, text=True, timeout=120)
        return {'returncode': p.returncode, 'stdout': p.stdout, 'stderr': p.stderr}
    except subprocess.TimeoutExpired as e:
        return {'returncode': -1, 'stdout': '', 'stderr': 'timeout'}


if __name__ == '__main__':
    print(run_example_api_scraper())
