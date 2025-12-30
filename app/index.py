import re
import signal
import time
import os
from pyarr import RadarrAPI
from pyarr import SonarrAPI
from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer
from jellyfin_apiclient_python import JellyfinClient


JELLYFIN_ADDRESS = os.getenv('JELLYFIN_ADDRESS')
JELLYFIN_API_KEY = os.getenv('JELLYFIN_API_KEY')

RADARR_CATEGORY = os.getenv('RADARR_CATEGORY')
RADARR_HOST = os.getenv('RADARR_HOST')
RADARR_API_KEY = os.getenv('RADARR_API_KEY')

SONARR_CATEGORY = os.getenv('SONARR_CATEGORY')
SONARR_HOST = os.getenv('SONARR_HOST')
SONARR_API_KEY = os.getenv('SONARR_API_KEY')

NZBGET_DIR = os.getenv('NZBGET_DIR').rstrip(os.sep)
VIDEO_EXTENSIONS = tuple(os.getenv('VIDEO_EXTENSIONS').split(','))


jellyfin = JellyfinClient()
jellyfin.config.data['app.name'] = 'streaming'
jellyfin.config.data['app.version'] = '1.0.0'
jellyfin.config.data['auth.ssl'] = False
jellyfin.authenticate({"Servers": [{"AccessToken": JELLYFIN_API_KEY, "address": JELLYFIN_ADDRESS}]}, discover=False)

CATEGORIES = [
    RADARR_CATEGORY,
    SONARR_CATEGORY,
]

radarr = RadarrAPI(RADARR_HOST, RADARR_API_KEY)
sonarr = SonarrAPI(SONARR_HOST, SONARR_API_KEY)

class GracefulKiller:
  kill_now = False

  def __init__(self):
    signal.signal(signal.SIGINT, self.exit_gracefully)
    signal.signal(signal.SIGTERM, self.exit_gracefully)

  def exit_gracefully(self, signum, frame):
    self.kill_now = True

class MyEventHandler(FileSystemEventHandler):
    def on_created(self, event: FileSystemEvent) -> None:
        path = event.src_path
        if not event.is_directory and is_video(path) and not is_sample(path):
            process_radarr(path)
            process_sonarr(path)

def is_video(path: str):
    return path.lower().endswith(VIDEO_EXTENSIONS)

def is_sample(path: str):
    return 'sample' in path.lower()

def get_category(path: str):
    cat = path.replace(NZBGET_DIR + os.sep, '').split(os.sep)[0]
    if cat in CATEGORIES:
        return cat
    return ''

def get_release_name(path: str) -> str | None:
    return path.replace(NZBGET_DIR + os.sep, '').split(os.sep)[1]

def get_radarr_path(release_name: str) -> str | None:
    queue = radarr.get_queue(include_unknown_movie_items=False, page_size=100)
    for record in queue['records']:
        if record['title'] == release_name:
            queue_detail = radarr.get_queue_details(record['movieId'], include_movie=True)[0]
            return queue_detail['movie']['folderName']
    return None

def get_sonarr_path(release_name: str) -> str | None:
    queue = sonarr.get_queue(include_series=True, include_unknown_series_items=False, page_size=100)
    for record in queue['records']:
        if record['title'] == release_name:
            return record['series']['path']
    return None

def get_season(path: str):
    regex = r"s(?P<season>\d+)e(?P<episode>\d+)"
    matches = re.search(regex, path.lower())
    if matches:
        return int(matches['season'])
    return None

def is_episode(path: str):
    regex = r"s(?P<season>\d+)e(?P<episode>\d+)"
    matches = re.search(regex, path.lower())
    return bool(matches)

def hardlink(src: str, dest: str):
    dest_dir = os.path.dirname(dest)
    os.makedirs(dest_dir, exist_ok=True)

    if not os.path.exists(src):
        print(f"Source file does not exist: {src}", flush=True)
        return

    if os.path.exists(dest):
        print(f"Removing already existing target file: {dest}", flush=True)
        os.remove(dest)

    os.link(src, dest)
    jellyfin.jellyfin.refresh_library()

def process_radarr(path: str):
    if get_category(path) != RADARR_CATEGORY:
        return
    release_name = get_release_name(path)
    failed_counter = 0
    radarr_path = None
    while not radarr_path and failed_counter < 10:
        radarr_path = get_radarr_path(release_name)
        if not radarr_path:
            failed_counter += 1
            radarr.post_command('RefreshMonitoredDownloads')
            time.sleep(3)
    if radarr_path:
        radarr_path = radarr_path + os.sep + release_name + os.path.splitext(path)[1]
        print(radarr_path, flush=True)
        hardlink(path, radarr_path)


def process_sonarr(path: str):
    if get_category(path) != SONARR_CATEGORY:
        return
    season = get_season(path)
    if season != None:
        release_name = get_release_name(path)
        failed_counter = 0
        sonarr_path = None
        while not sonarr_path and failed_counter < 10:
            sonarr_path = get_sonarr_path(release_name)
            if not sonarr_path:
                failed_counter += 1
                radarr.post_command('RefreshMonitoredDownloads')
                time.sleep(3)
        if sonarr_path:
            file_name = os.path.basename(path)
            if is_episode(release_name):
                file_name = release_name + os.path.splitext(path)[1]
            sonarr_path = sonarr_path + os.sep + 'Season ' + str(season) + os.sep + file_name
            print(sonarr_path, flush=True)
            hardlink(path, sonarr_path)

def main():
    event_handler = MyEventHandler()
    observer = Observer()
    observer.schedule(event_handler, NZBGET_DIR, recursive=True)
    observer.start()
    try:
        killer = GracefulKiller()
        while not killer.kill_now:
            time.sleep(1)
    finally:
        observer.stop()
        observer.join()

if __name__ == "__main__":
    main()
