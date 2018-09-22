#!/usr/bin/python

import os, os.path
import sys
import datetime
import time
import syslog
import re

# TODO: Read these settings from a config. file
KEEP_DAYS = 7
REC_DIR = "/var/lib/fruitnanny"
DATE_FORMAT = "%Y-%m-%d_%H:%M:%S"

# Calculate the purge cutoff date
oldest_kept = datetime.datetime.now() - datetime.timedelta(days=KEEP_DAYS)
# Create regex for extracting date from filename
file_regex = re.compile("\\.*(\\d{4})-(\\d\\d)-(\\d\\d)_(\\d\\d):(\\d\\d):(\\d\\d)\\..*")

# Loop through the recording files
files = sorted(os.listdir(REC_DIR))
for filename in files:
    filename_match = file_regex.match(filename)
    if not filename_match:
        continue
    # Construct a date object from the filename elements
    file_year = int(filename_match.group(1))
    file_month = int(filename_match.group(2))
    file_day = int(filename_match.group(3))
    file_hour = int(filename_match.group(4))
    file_minute = int(filename_match.group(5))
    file_second = int(filename_match.group(6))
    file_date = datetime.datetime(file_year, file_month, file_day, file_hour, file_minute, file_second)
    # Delete the file if the date < purge cutoff date
    if file_date < oldest_kept:
        # Delete the file
        syslog.syslog("Deleting recording " + REC_DIR + os.sep + filename)
        os.remove(REC_DIR + os.sep + filename)
