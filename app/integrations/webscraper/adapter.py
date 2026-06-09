import subprocess, json, os, shlex

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(__file__)))
VENDOR = os.path.join(ROOT, 'vendor', 'web-scraper')

def run_example_api_scraper(ids=[123]):
    js = os.path.join(VENDOR, 'examples', 'api-scraper.js')
    cmd = f"node {shlex.quote(js)}"
    p = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=60)
    return {'returncode': p.returncode, 'stdout': p.stdout, 'stderr': p.stderr}

if __name__ == '__main__':
    print(run_example_api_scraper())
