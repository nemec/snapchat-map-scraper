#!/usr/bin/env python3

import time
import requests
import json
import sys
import sqlite3
import argparse
import pathlib
import subprocess
import os
import select
import shutil
import datetime


def create_database(db_file: pathlib.Path):
    base_folder = pathlib.Path('sql')
    sql_files = [
        base_folder / 'locations.sql',
        base_folder / 'media.sql'
    ]

    with sqlite3.connect(str(db_file)) as conn:
        cur = conn.cursor()
        try:
            for sql in sql_files:
                with sql.open('r') as f:
                    cur.executescript(f.read())
        finally:
            conn.commit()
            cur.close()


def add_location(db_file: pathlib.Path, lat: float, lon: float, zoom: float, label: str):
    with sqlite3.connect(str(db_file)) as conn:
        cur = conn.cursor()
        try:
            cur.execute('INSERT INTO locations (latitude, longitude, zoom, label) '
                        'VALUES (?, ?, ?, ?)', (lat, lon, zoom, label))
        finally:
            conn.commit()
            cur.close()


def randomize_location(latitude, longitude, radius):
    import random
    import math

    # https://gis.stackexchange.com/a/68275
    deg = radius / 111000.0 # convert from meters to degrees
    u = random.random()
    v = random.random()
    w = deg * math.sqrt(u)
    t = 2 * math.pi * v
    x = w * math.cos(t)
    y = w * math.sin(t)
    # Adjust the x-coordinate for the shrinking of the east-west distances
    new_x = x / math.cos(math.radians(longitude))

    return (new_x + latitude, y + longitude)

def get_latest_tileset():
    url = 'https://ms.sc-jpl.com/web/getLatestTileSet'
    headers = {
        'content-type': 'application/json'
    }
    resp = requests.post(url, headers=headers, json={})
    resp.raise_for_status()
    return resp.json()

def get_epoch():
    tiles = get_latest_tileset()
    for t in tiles['tileSetInfos']:
        if t['id']['type'] == 'HEAT':
            return int(t['id']['epoch'])
    return 0


def download_file(file: pathlib.Path, url: str):
    if file.exists():
        return
    with requests.get(url, stream=True) as resp:
        resp.raise_for_status()
        with open(str(file), 'wb') as f:
            for chunk in resp.iter_content(chunk_size=8192):
                f.write(chunk)


def download_media(idnum, preview_url, media_url, overlay_url):
    base_folder = pathlib.Path('media')
    if not base_folder.exists():
        base_folder.mkdir(parents=True)
    media_file = None
    preview_file = None
    overlay_file = None

    if media_url:
        media_file = (base_folder / idnum).with_suffix('.mp4')
        download_file(media_file, media_url)

    if preview_url:
        preview_file = (base_folder / idnum).with_suffix('.jpg')
        download_file(preview_file, preview_url)

    if overlay_url:
        overlay_file = (base_folder / (idnum + '_overlay')).with_suffix('.png')
        download_file(overlay_file, overlay_url)

    return (str(preview_file) if preview_file is not None else None,
            str(media_file) if media_file is not None else None,
            str(overlay_file) if overlay_file is not None else None)



def scrape_location(db_file: pathlib.Path, location_id, latitude, longitude, zoom, randomize, epoch=None):
    if epoch is None:
        epoch = get_epoch()
    if epoch == 0:
        print('Error getting latest Snapchat tile data')
        sys.exit(1)

    if randomize:
        latitude, longitude = randomize_location(latitude, longitude, 1609.0)
    
    data = {
        "requestGeoPoint":{
            "lat": latitude,
            "lon": longitude
        },
        "zoomLevel": zoom,
        "tileSetId": {
            "flavor": "default",
            "epoch": epoch,
            "type": 1
        },
        #"radiusMeters": 87.96003668860504,
        "radiusMeters": 500.0, # 1 mi
        "maximumFuzzRadius": 0
    }

    headers = {
        'Content-Type': 'application/json'
    }

    url = 'https://ms.sc-jpl.com/web/getPlaylist'

    resp = requests.post(url, json=data, headers=headers)
    resp.raise_for_status()
    j = resp.json()
    new_records = 0
    for vid in j['manifest']['elements']:
        idnum = vid['id']
        duration_s = vid.get('duration')
        timestamp = vid.get('timestamp')
        
        info = vid['snapInfo']
        titles = info['title']['strings']
        title = [t['text'] for t in titles if t['locale'] == 'en']
        if title:
            title = title[0]
        else:
            title = info['title'].get('fallback')
        overlay_text = info.get('overlayText')

        media = info.get('streamingMediaInfo')
        preview_url = None
        media_url = None
        overlay_url = None
        if media:
            if media.get('previewUrl'):
                preview_url = media['prefixUrl'] + media['previewUrl']
            if media.get('mediaUrl'):
                media_url = media['prefixUrl'] + media['mediaUrl']
            if media.get('overlayUrl'):
                overlay_url = media['prefixUrl'] + media['overlayUrl']
                if not overlay_url.endswith('png'):
                    print(f'Overlay url: {overlay_url}')
        else:
            media = info.get('publicMediaInfo')
            if media:
                preview_url = media['publicImageMediaInfo']['mediaUrl']
            #else:
            #    media = info.get
            #    print('Unable to get video info')
            #    print(json.dumps(vid))
            #    continue
            
        try:
            (preview_path, media_path, overlay_path) = download_media(idnum, preview_url, media_url, overlay_url)
        except requests.HTTPError:
            pass

        with sqlite3.connect(str(db_file)) as conn:
            cur = conn.cursor()
            try:
                sel = cur.execute('SELECT EXISTS(SELECT 1 FROM media WHERE id=?)', (idnum,))
                if sel.fetchone() == (1,):
                    continue
                cur.execute('INSERT INTO media '
                    '(id, location_id, duration_seconds, timestamp, title, preview_path, media_path, overlay_path, overlay_text) '
                    'VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)',
                    (idnum, location_id, duration_s, timestamp, title, preview_path, media_path, overlay_path, overlay_text))
                conn.commit()
                new_records += 1
            finally:
                cur.close()

    return new_records


def scrape_locations(db_file: pathlib.Path, randomize, repeat, sleep, label):
    locations = []
    with sqlite3.connect(str(db_file)) as conn:
        cur = conn.cursor()
        if label is None:
            locations = list(cur.execute('SELECT id, latitude, longitude, zoom, label FROM locations'))
        else:
            locations = list(cur.execute('SELECT id, latitude, longitude, zoom, label FROM locations WHERE label=?', (label,)))

    try:
        while True:
            for loc in locations:
                epoch = get_epoch()
                new = scrape_location(db_file, loc[0], loc[1], loc[2], loc[3], randomize, epoch)
                combined = f'{loc[1], loc[2]}'
                if new > 0:
                    print(f'Scraped {new} media from location {loc[4] or combined}')
                else:
                    print(f'No new media from location {loc[4] or combined}')
            if not repeat:
                break
            print(f'Sleeping for {sleep} seconds...')
            time.sleep(sleep)
    except KeyboardInterrupt:
        pass


def review(db_file: pathlib.Path, exe: str, label=None):
    base_folder = pathlib.Path('.')
    media = []
    with sqlite3.connect(str(db_file)) as conn:
        cur = conn.cursor()
        if label is None:
            media = list(cur.execute('SELECT id, media_path FROM media m JOIN locations l WHERE reviewed=0 AND media_path IS NOT NULL ORDER BY timestamp ASC'))
        else:
            media = list(cur.execute('SELECT id, media_path FROM media m JOIN locations l WHERE l.label = ? AND reviewed=0 AND media_path IS NOT NULL ORDER BY timestamp ASC', (label,)))
    for idx, (idnum, v) in enumerate(media):
        subprocess.call([exe, base_folder / v], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        # Flush all accidental double Return key presses
        while select.select([sys.stdin.fileno()], [], [], 0.0)[0]:
            os.read(sys.stdin.fileno(), 4096)
        classification = input('Classify or leave blank:')
        if not classification:
            classification = None
        cur.execute('UPDATE media SET reviewed=1, classification=? WHERE id=?', (classification, idnum))
        conn.commit()
        print(f'{len(media) - idx - 1} remaining')


def export(db_file: pathlib.Path, export_dir: pathlib.Path):
    base_folder = pathlib.Path('.')
    if not export_dir.exists():
        export_dir.mkdir(parents=True)
    with sqlite3.connect(str(db_file)) as conn:
        cur = conn.cursor()
        files = list(cur.execute('SELECT media_path, timestamp, classification FROM media WHERE reviewed=1 AND classification IS NOT NULL'))
    for (media_path, timestamp, classification) in files:
        date = datetime.datetime.fromtimestamp(int(timestamp)/1000)
        date_str = date.strftime('%Y-%m-%d %H:%M:%S')
        media_file = base_folder / media_path
        fname = f'{date_str}-{classification}.mp4'
        dest = export_dir / fname
        if dest.exists():
            continue
        shutil.copy(str(media_file), str(dest))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    subp = parser.add_subparsers(dest='subparser_name')

    create_p = subp.add_parser('create', help='Create an empty sqlite database for storing results')
    create_p.add_argument('database', type=pathlib.Path, default=pathlib.Path('data.db'),
                        nargs='?', help='Database file')

    add_loc_p = subp.add_parser('add', help='Add a new location to the scan database')
    add_loc_p.add_argument('--database', type=pathlib.Path, default=pathlib.Path('data.db'))
    add_loc_p.add_argument('latitude', type=float, help='Area of interest latitude')
    add_loc_p.add_argument('longitude', type=float, help='Area of interest latitude')
    # Note - I don't know how zoom affects search results
    #add_loc_p.add_argument('zoom', type=float, nargs='?', default=16.0,
    #    help='Area of interest zoom level. Floating point number between 0 and 22. '
    #         'See for more info: https://docs.mapbox.com/help/glossary/zoom-level/')
    add_loc_p.add_argument('--label', type=str, help='A label used to describe the location')

    scrape_p = subp.add_parser('scrape', help='Scrape new media')
    scrape_p.add_argument('--database', type=pathlib.Path, default=pathlib.Path('data.db'),
                        nargs='?', help='Database file')
    scrape_p.add_argument('--randomize', action='store_true',
                        help='Randomize the location point within one mile')
    scrape_p.add_argument('--repeat', action='store_true',
                        help='Repeatedly scrape results in a loop until stopped.')
    scrape_p.add_argument('--sleep', type=int, default=120,
                        help='Number of seconds to sleep between repeats (if repeat is enabled). Default 120 seconds.')
    scrape_p.add_argument('label', type=str, nargs='?',
        help='Optionally scrape a specifically labeled location. By default scrapes all locations.')

    reviwe_p = subp.add_parser('review', help='Review any unreviewed videos')
    reviwe_p.add_argument('--database', type=pathlib.Path, default=pathlib.Path('data.db'),
                        nargs='?', help='Database file')
    reviwe_p.add_argument('--player', type=pathlib.Path, default=pathlib.Path('/usr/bin/totem'),
                        help='Media player executable path. Must take video as only argument')
    reviwe_p.add_argument('label', type=str, nargs='?',
        help='Optionally review only a specifically labeled location. By default reviews all locations.')

    reviwe_p = subp.add_parser('export', help='Export classified videos to a folder')
    reviwe_p.add_argument('--database', type=pathlib.Path, default=pathlib.Path('data.db'),
                        nargs='?', help='Database file')
    reviwe_p.add_argument('export_dir', type=pathlib.Path,
        help='Directory to export files.')

    args = parser.parse_args()
    if args.subparser_name == 'create':
        if args.database.exists():
            print(f"Database file '{args.database}' already exists.")
            sys.exit(1)
        create_database(args.database)
        sys.exit(0)

    if not args.database.exists():
        print(f"Database file '{args.database}' does not exist")
        sys.exit(1)

    if args.subparser_name == 'add':
        add_location(args.database, args.latitude, args.longitude, 16, args.label)
    elif args.subparser_name == 'scrape':
        scrape_locations(args.database, args.randomize, args.repeat, args.sleep, args.label)
    elif args.subparser_name == 'review':
        review(args.database, args.player, args.label)
    elif args.subparser_name == 'export':
        export(args.database, args.export_dir)