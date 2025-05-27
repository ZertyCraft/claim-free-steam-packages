import random
import sys
from datetime import timedelta

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from requests_cache import CachedSession
from joblib import Parallel, delayed
from tqdm import tqdm

# --- Configuration ----------------------------------------------------------

API_LIST_URL = 'https://api.steampowered.com/ISteamApps/GetAppList/v2'
DETAILS_URL   = 'https://store.steampowered.com/api/appdetails'

# Proxy (if you really need it)
PROXIES = {
    'http':  'socks5h://p.webshare.io:9999',
    'https': 'socks5h://p.webshare.io:9999',
}

# How many times to retry on transient errors
MAX_RETRIES = 3

# How many parallel workers
N_JOBS = 20

# -----------------------------------------------------------------------------


def make_session():
    """Return a CachedSession with proper HTTP retry logic."""
    session = CachedSession(
        cache_name='steam_cache',
        backend='filesystem',
        expire_after=timedelta(hours=random.randint(20, 24)),
        allowable_methods=['GET'],
        allowable_codes=[200],
        stale_if_error=False,
    )

    # mount retries for non-cached and cached alike
    retry_strategy = Retry(
        total=MAX_RETRIES,
        status_forcelist=[429, 500, 502, 503, 504],
        backoff_factor=1,
        allowed_methods=["GET"],
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("https://", adapter)
    session.mount("http://", adapter)

    session.proxies = PROXIES
    session.headers.update({
        'User-Agent': 'my-steam-agent/1.0'
    })
    return session


def check_game(session, appid):
    """Return appid if it’s a paid, released, free game; else None."""
    params = {
        'appids': appid,
        'cc': 'US',
        'l': 'english',
        'v': 1
    }

    try:
        resp = session.get(DETAILS_URL, params=params, timeout=10)
        resp.raise_for_status()
        payload = resp.json()
    except (requests.RequestException, ValueError) as e:
        print(f"[App {appid}] request failed: {e}")
        return None

    appdata = payload.get(str(appid), {})
    if not appdata.get('success'):
        return None

    info = appdata['data']
    # not yet released
    if info.get('release_date', {}).get('coming_soon'):
        return None
    # free game
    if info.get('is_free'):
        return appid
    return None


def main():
    # 1) fetch the master app list
    try:
        all_apps = requests.get(API_LIST_URL, timeout=10).json()['applist']['apps']
    except Exception as e:
        print(f"Failed to fetch app list: {e}")
        sys.exit(1)

    app_ids = [a['appid'] for a in all_apps]
    random.shuffle(app_ids)
    print(f"Received {len(app_ids)} apps")

    session = make_session()

    # 2) check them in parallel, with progress bar
    with tqdm(total=len(app_ids), desc="Requesting app statuses", mininterval=10) as pbar:
        def task(a):
            result = check_game(session, a)
            pbar.update(1)
            return result

        results = Parallel(n_jobs=N_JOBS)(delayed(task)(aid) for aid in app_ids)

    # 3) write only the ones that returned non-None
    free_apps = [str(r) for r in results if r is not None]
    if not free_apps:
        print("No free apps found, something’s off.")
        sys.exit(1)

    output = ",".join(free_apps)
    with open('package_list.txt', 'w') as f:
        f.write(output)

    print("\nRan successfully; wrote", len(free_apps), "app IDs.")


if __name__ == '__main__':
    main()
