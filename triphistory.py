#!/usr/bin/env python3
# created by gemini
# I would like to create a python script that accepts a source directory and a YAML file
# as arguments. The source directory holds photographs, they are in subdirectories of 
# the form YYYY/YYYY-MM-DD, the YAML file holds arrays of trip names, start and end dates 
# in the format YYYY-MM-DD, the script should create in a target directory new sub directories
# with the trip start date and the trip name, and in side that directory should be symlinks 
# to files from the source directory that where their parent directories match between the 
# YAML start and end dates, the script should ignore any other symlinks in the source directory 
# and directories that do not match the provided pattern
# could you add the source and target parameters as fields in the YAML file instead

# ./triphistory.py trips.yaml

# and the yaml looks like this:
# source: "/path/to/your/source_photos"
# target: "/path/to/your/target_output_directory"
# trips:
#   - name: "Summer Vacation to Italy"
#     start_date: "2023-07-15"
#     end_date: "2023-07-30"
#   - name: "Weekend Mountain Hike"
#     start_date: "2023-08-05"
#     end_date: "2023-08-06"

import os
import re
import sys
import yaml
import signal
import logging
import argparse
from datetime import datetime, timedelta
from pathlib import Path

# ----------------------------------------------------------------------------

def signal_handler(sig, frame):
    """ """

    logging.info("Ctrl+C pressed!")
    sys.exit(0)


signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGHUP, signal_handler)


def abort_handler(sig, frame):
    """ """

    logging.info("Ctrl+C pressed!")
    sys.exit(0)


signal.signal(signal.SIGHUP, abort_handler)

# --- Logging Setup ---
def setup_logging(log_level_str="INFO"):
    """Configures logging for the script."""
    numeric_level = getattr(logging, log_level_str.upper(), None)
    if not isinstance(numeric_level, int):
        raise ValueError(f'Invalid log level: {log_level_str}')

    logging.basicConfig(
        level=numeric_level,
        format='%(asctime)s - %(levelname)s - %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )


def parse_date(date_str):
    return datetime.strptime(date_str, "%Y-%m-%d").date()

def date_in_trip(date, trip):
    start = parse_date(trip['start_date'])
    end = parse_date(trip['end_date'])
    return start <= date <= end

def date_adjacent_to_trip(date, trip):
    start = parse_date(trip['start_date'])
    end = parse_date(trip['end_date'])
    return (date == start - timedelta(days=1)) or (date == end + timedelta(days=1))

def extend_trip_to_include_date(trip, date):
    start = parse_date(trip['start_date'])
    end = parse_date(trip['end_date'])
    if date < start:
        trip['start_date'] = date.strftime("%Y-%m-%d")
    elif date > end:
        trip['end_date'] = date.strftime("%Y-%m-%d")

def update_missing_trips(missing_trips, date):
    for entry in missing_trips:
        start = parse_date(entry['start_date'])
        end = parse_date(entry['end_date'])
        if start - timedelta(days=1) <= date <= end + timedelta(days=1):
            # Extend the range if needed
            if date < start:
                entry['start_date'] = date.strftime("%Y-%m-%d")
            elif date > end:
                entry['end_date'] = date.strftime("%Y-%m-%d")
            # Update name after possible extension
            start_str = entry['start_date']
            end_str = entry['end_date']
            days = (parse_date(end_str) - parse_date(start_str)).days + 1
            if start_str == end_str:
                entry['name'] = f"{start_str} day"
            else:
                entry['name'] = f"{start_str} to {end_str} ({days} days)"
            return
    # If not found, add new entry
    name = f"{date.strftime('%Y-%m-%d')} day trip"
    missing_trips.append({
        'name': name,
        'start_date': date.strftime("%Y-%m-%d"),
        'end_date': date.strftime("%Y-%m-%d")
    })
        
def preprocess_trips_config(yaml_config_file):
    # Load YAML
    with open(yaml_config_file, 'r') as f:
        config = yaml.safe_load(f)

    source_dir = Path(config['source'])
    trips = config.get('trips', [])
    missing_trips = config.get('missing_trips', [])

    # Find all YYYY-MM-DD directories in source_dir
    found_dates = set()
    for year_dir in source_dir.iterdir():
        if not year_dir.is_dir() or not re.match(r'^\d{4}$', year_dir.name):
            continue
        for day_dir in year_dir.iterdir():
            if day_dir.is_dir() and re.match(r'^\d{4}-\d{2}-\d{2}$', day_dir.name):
                found_dates.add(parse_date(day_dir.name))

    # Process each found date
    for date in sorted(found_dates):
        matched = False
        for trip in trips:
            if date_in_trip(date, trip):
                matched = True
                break
            if date_adjacent_to_trip(date, trip):
                extend_trip_to_include_date(trip, date)
                matched = True
                break
        if not matched:
            update_missing_trips(missing_trips, date)

    # Save back missing_trips to config
    config['missing_trips'] = missing_trips
    return config


def process_trips_from_config_dict(config, dry_run: bool = False):
    """
    Processes trips from a config dictionary (not a YAML file path).
    """
    source_dir = Path(config['source'])
    target_dir = Path(config['target'])
    trips_data = config.get('trips', [])

    logging.info(f"Using source directory: '{source_dir}' (from YAML)")
    logging.info(f"Using target directory: '{target_dir}' (from YAML)")

    # Create target directory if it doesn't exist
    if not dry_run:
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            logging.error(f"Error: Could not create target directory '{target_dir}': {e}")
            sys.exit(1)
    else:
        logging.info(f"[DRY RUN] Would ensure target directory exists: '{target_dir}'")

    # Iterate through each trip defined in the config
    for i, trip_info in enumerate(trips_data):
        trip_name = trip_info.get('name', f"trip_{i+1}")
        start_date_str = trip_info['start_date']
        end_date_str = trip_info['end_date']
        trip_start_date = parse_date(start_date_str)
        trip_end_date = parse_date(end_date_str)
        # easy fix directory path issues with slashes
        trip_dir_name = trip_name.replace("/", "_").replace("\\", "_")
        year_str = start_date_str[:4]
        current_trip_target_path = Path(os.path.join(target_dir, year_str, trip_dir_name))

        if not dry_run:
            try:
                current_trip_target_path.mkdir(parents=True, exist_ok=True)
                logging.info(f"\nProcessing trip: '{trip_name}' -> '{current_trip_target_path}'")
            except OSError as e:
                logging.warning(f"Warning: Could not create directory for trip '{trip_name}' ('{current_trip_target_path}'): {e}. Skipping this trip.")
                continue
        else:
            logging.info(f"\n[DRY RUN] Would create directory for trip: '{trip_name}' -> '{current_trip_target_path}'")

        photos_linked_for_trip = 0
        for year_dir in source_dir.iterdir():
            if not year_dir.is_dir() or not re.match(r'^\d{4}$', year_dir.name):
                continue
            for day_dir in year_dir.iterdir():
                if day_dir.is_dir() and re.match(r'^\d{4}-\d{2}-\d{2}$', day_dir.name):
                    photo_date = parse_date(day_dir.name)
                    if trip_start_date <= photo_date <= trip_end_date:
                        logging.info(f"  Found matching date directory: '{day_dir.name}'")
                        for photo_file_path in day_dir.iterdir():
                            if photo_file_path.is_file() and not photo_file_path.is_symlink():
                                symlink_name = photo_file_path.name
                                symlink_path_in_trip_dir = current_trip_target_path / symlink_name
                                absolute_source_photo_path = photo_file_path.resolve()

                                if symlink_path_in_trip_dir.exists() or symlink_path_in_trip_dir.is_symlink():
                                    logging.warning(f"Symlink target '{symlink_path_in_trip_dir}' already exists. Skipping.")
                                else:
                                    if dry_run:
                                        logging.info(f"    [DRY RUN] Would link: '{absolute_source_photo_path}' -> '{symlink_path_in_trip_dir}'")
                                        photos_linked_for_trip += 1
                                    else:
                                        try:
                                            symlink_path_in_trip_dir.symlink_to(absolute_source_photo_path)
                                            logging.info(f"    Linked: '{absolute_source_photo_path}' -> '{symlink_path_in_trip_dir}'")
                                            photos_linked_for_trip += 1
                                        except OSError as e:
                                            logging.error(f"    Error creating symlink for '{photo_file_path.name}': {e}")
                                        except Exception as e:
                                            logging.error(f"    An unexpected error occurred creating symlink for '{photo_file_path.name}': {e}")
        if photos_linked_for_trip == 0:
            logging.info(f"  No photos found/linked for trip '{trip_name}' within the date range {start_date_str} to {end_date_str}.")

def main():
    parser = argparse.ArgumentParser(
        description="Organize photos into trip directories using symlinks. "
                    "Configuration (source/target dirs, trip details) is read from a YAML file."
    )
    parser.add_argument(
        "yaml_config_file",
        type=Path,
        help="YAML file containing 'source', 'target', and a list of 'trips'. "
             "Each trip entry should be a dictionary with 'name', 'start_date' (YYYY-MM-DD), "
             "and 'end_date' (YYYY-MM-DD)."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done, but do not create directories or symlinks."
    )
    parser.add_argument(
        "--log-level",
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"],
        help="Set the logging level (default: INFO)."
    )

    args = parser.parse_args()
    setup_logging(args.log_level)

    if args.dry_run:
        logging.info("*** Starting DRY RUN mode. No files will be changed. ***")

    config = preprocess_trips_config(args.yaml_config_file)
    # --- Write updated config back to YAML file ---
    
    if not args.dry_run:
        with open(args.yaml_config_file, "w") as f:
            yaml.safe_dump(config, f, sort_keys=False, default_flow_style=False)
        logging.info(f"Updated config written to {args.yaml_config_file}")

    process_trips_from_config_dict(config, dry_run=args.dry_run)
    logging.info("\nPhoto organization process complete.")


if __name__ == "__main__":
    main()
