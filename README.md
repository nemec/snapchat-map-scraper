# Snapchat Story Downloader

This program can search Snapchat's public [Snap Map](https://map.snapchat.com/)
at multiple locations and download all stories for later investigation and
categorization. A lot is unknown about how Snapchat decides which videos show
up at which "point" on the map, so the scraper can also randomize the geolocation
where it scrapes from by a few hundred meters to hopefully convince the API
to give you a few more relevant videos.

This has been tested on Linux, but should work on Windows/Mac as well with
a video viewer installed.


## Install Instructions

```bash
git clone https://github.com/nemec/snapchat-map-scraper.git
cd snapchat-map-scraper/
python3 -m venv env  # create virtual environment
source env/bin/activate  # activate virtual environment
pip3 install -r requirements.txt
```


## Usage

Follow each step in order. Also, ensure you have activated your virtual
environment, otherwise the packages will be missing.

### Create Database

This database holds data related to one group of search queries. Since SQLite
produces database files with little overhead, you should create a new database
each time you want to sample data.

```bash
python3 story_downloader.py create snap.db
```

### Add locations

The 