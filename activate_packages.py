import random
import sys
from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed

import requests
from requests.adapters import HTTPAdapter
from tqdm import tqdm
from urllib3.util.retry import Retry

# ── Configuration ───────────────────────────────────────────────

API_LIST_URL = 'https://api.steampowered.com/ISteamApps/GetAppList/v2'
DETAILS_URL   = 'https://store.steampowered.com/api/appdetails'

PROXIES = {
    'http':  'socks5h://p.webshare.io:9999',
    'https': 'socks5h://p.webshare.io:9999',
}

MAX_RETRIES = 3
N_THREADS   = 20
TIMEOUT     = 10  # seconds

# ── Helper functions ────────────────────────────────────────────

def make_session():
    """Build a requests.Session with retry logic."""
    session = requests.Session()
    retry = Retry(
        total=MAX_RETRIES,
        backoff_factor=1,
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["GET"],
    )
    adapter = HTTPAdapter(max_retries=retry)
    session.mount("https://", adapter)
    session.mount("http://", adapter)

    session.proxies = PROXIES
    session.headers.update({
        'User-Agent': 'my-steam-agent/1.0'
    })
    return session

def check_game(session, appid):
    """
    Return the appid if it’s a free, released game; else None.
    """
    try:
        resp = session.get(
            DETAILS_URL,
            params={'appids': appid, 'cc': 'US', 'l': 'english', 'v': 1},
            timeout=TIMEOUT
        )
        resp.raise_for_status()
        data = resp.json().get(str(appid), {})
    except Exception as e:
        # network error, JSON error, HTTP error...
        # print(f"[{appid}] failed: {e}")
        return None

    if not data.get('success', False):
        return None

    info = data['data']
    # not yet released?
    if info.get('release_date', {}).get('coming_soon', False):
        return None
    # free?
    if info.get('is_free', False):
        return appid
    return None

# ── Main ───────────────────────────────────────────────────────

def main():
    # 1) fetch the master app list
    try:
        applist = requests.get(API_LIST_URL, timeout=TIMEOUT).json()
        app_ids = [a['appid'] for a in applist['applist']['apps']]
    except Exception as e:
        print(f"Failed to fetch app list: {e}")
        sys.exit(1)

    random.shuffle(app_ids)
    print(f"Received {len(app_ids)} apps")

    # 2) spin up a shared session + thread pool
    session = make_session()
    free_apps = []

    with ThreadPoolExecutor(max_workers=N_THREADS) as exe:
        futures = {exe.submit(check_game, session, aid): aid for aid in app_ids}
        for fut in tqdm(as_completed(futures),
                        total=len(app_ids),
                        desc="Requesting app statuses",
                        mininterval=5):
            res = fut.result()
            if res is not None:
                free_apps.append(str(res))

    # 3) write output
    if not free_apps:
        print("No free apps found; something’s off.")
        sys.exit(1)

    out_str = ",".join(free_apps)
    with open('package_list.txt', 'w') as f:
        f.write(out_str)

    print(f"\nRan successfully; found {len(free_apps)} free games.")

if __name__ == "__main__":
    main()
