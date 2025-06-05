#!/usr/bin/env python3
# created by gemini
# I am looking for an application that runs in the terminal on a raspberry pi, it must be able to 
# accept a directory of photographs as an input and move any found photographs into a new 
# directory of the format YYYY/MM/YYYY-MM-DD, maintain file names and exact duplicates removed 
# but duplicates with the same name but not identical should be given a new unique name
# it needs to be able to support RAW file formats such as "DNG",
# "CIB"
# "NEF", "NRW",
# "JPG", "JPEG",
# "ORF", "OIF",
# "CR2", "CR3",
# "RAW","RW2",
# "FFF", "3PR", "3FR",
# "ARW", "SR2", "SRF", "CRAW",
# "RWL",
# "RAF",
# "SRW","AVI",
# "MP4","MOV"
# Ive had more success extracting EXIF information with the piexif module, could you use that. 
# also the file extensions need to be case insensitive as do any filename checks
# can you add an option to copy instead of move

import os
import re
import shutil
import signal
import hashlib
import argparse
import logging
from datetime import datetime, timedelta, timezone
from stat import *
import piexif # Changed from Pillow for EXIF

# Supported file extensions (case-insensitive)
# Includes common image, RAW, and some video formats
ALL_EXTENSIONS = (
    # Standard Images
    '.jpg', '.jpeg', '.png', '.gif', '.bmp', '.tiff', '.webp', '.heic', '.heif',
    # RAW Formats
    '.dng',                                 # Adobe Digital Negative
    '.cib',                                 # CorelDRAW CIB (less common as camera RAW)
    '.nef', '.nrw',                         # Nikon
    '.orf',                                 # Olympus
    '.oif',                                 # Olympus Image Format (container)
    '.cr2', '.cr3', '.craw',                # Canon
    '.raw', '.rw2',                         # Panasonic
    '.fff', '.3pr', '.3fr',                 # Hasselblad, Imacon
    '.arw', '.sr2', '.srf',                 # Sony
    '.rwl',                                 # Leica
    '.raf',                                 # Fujifilm
    '.srw',                                 # Samsung
    # Video Formats
    '.avi', '.mp4', '.mov'
)

REQUIRED_TAGS = [
    "DateTimeOriginal",
    "OffsetTimeOriginal",
]

# Define which extensions are typically non-image/video for EXIF purposes if needed
# For piexif, we'll attempt EXIF on most non-video files.
VIDEO_EXTENSIONS = ('.avi', '.mp4', '.mov')

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

# ----------------------------------------------------------------------------
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


# ----------------------------------------------------------------------------
def is_valid_extension(filename, extensions):
    """
    Validates if the filename has an extension from the provided list.

    Args:
        filename (str): The name of the file to validate.
        extensions (list): A list of allowed extensions.

    Returns:
        bool: True if the filename has a valid extension, False otherwise.
    """
    return any(filename.lower().endswith(ext.lower()) for ext in extensions)

# ----------------------------------------------------------------------------
def UTC_from_exif(original, offset):
  """
  Calculates UTC time from EXIF DateTimeOriginal and EXIF OffsetTimeOriginal.

  Args:
    original: String original datetime "YYYY:MM:DD HH:MM:SS"
    offset:   String   time offset "HH:MM:SS"

  Returns:
    UTC time "YYYY-MM-DD HH:MM:SS+00:00"
  """

  try:
    # Parse original
    # dt_obj = datetime.strptime(original, "%Y:%m:%d %H:%M:%S")
    # Try parsing with both possible formats
    try:
        dt_obj = datetime.strptime(original, "%Y:%m:%d %H:%M:%S")
    except ValueError:
        dt_obj = datetime.strptime(original, "%Y-%m-%d %H:%M:%S")

    
    if not offset:
      offset = "00:00"

    # Parse offset hours/minutes
    offset_hours, offset_minutes = map(int, offset.split(':'))
    offset_timedelta = timedelta(hours=offset_hours, minutes=offset_minutes)

    # Calculate UTC time
    utc_time = dt_obj - offset_timedelta

    # Convert to UTC timezone
    utc_time = utc_time.replace(tzinfo=timezone.utc)

    # Format UTC time as string
    return utc_time.strftime("%Y-%m-%d %H:%M:%S%z")

  except ValueError:
    #   possibly happens if time offset is bad
    logging.error(f"ValueError: Invalid datetime or offset format: {original}, {offset}, reseting to 1970")
    dt_obj = datetime.strptime("1970:01:01 00:00:00", "%Y:%m:%d %H:%M:%S")
    return dt_obj.strftime("%Y-%m-%d %H:%M:%S%z")
  except Exception as err:
    logging.error(f"{type(err).__name__} was raised: {err}")
    return dt_obj.strftime("%Y-%m-%d %H:%M:%S%z")

# ----------------------------------------------------------------------------

def get_file_ctime(file_path):
    """
    Get the creation date of a file.

    Args:
        file_path (str): The path to the file.

    Returns:
        datetime: The creation date of the file.
    """
    try:
        # Get the file's status
        stat_info = os.stat(file_path)
        # Get the creation time (st_ctime) and convert it to a datetime object
        creation_time = datetime.fromtimestamp(stat_info.st_ctime)
        # put it in the same format that exif uses
        return creation_time.strftime("%Y-%m-%d %H:%M:%S")
    except Exception as e:
        logging.error(f"Error getting creation date: {e}")
        return None


# ----------------------------------------------------------------------------
def extract_exif(file_path):
    """
    Extracts EXIF data from an image file and filters it based on REQUIRED_TAGS.

    Args:
        file_path (str): The path to the image file.

    Returns:
        dict: A dictionary containing the required EXIF tags and their values.
    """
    info = {}
    try:
        # Load the EXIF data from the image
        exif_data = piexif.load(file_path)

        # Filter and extract only the required tags
        for ifd_name in exif_data:
            if ifd_name == "Exif":
                for tag in exif_data[ifd_name]:
                    tag_name = piexif.TAGS[ifd_name].get(tag, {}).get("name", None)
                    if tag_name in REQUIRED_TAGS:
                        tag_value = exif_data[ifd_name][tag]
                        info[tag_name] = tag_value.decode( 'utf-8', errors='replace') if isinstance(tag_value, bytes) else tag_value
                    else:
                        # create empty tag if not found
                        info[tag_name] = ""
    except Exception as e:
        info["DateTimeOriginal"] = get_file_ctime(file_path)
        info["OffsetTimeOriginal"] = "00:00"
    
    # some cameras set a partially empty time offset
    if re.match(r"^\s*:", info.get("OffsetTimeOriginal", "")):
        info["OffsetTimeOriginal"] = "00:00"
    
    # if info.get("DateTimeOriginal"):
    #     info["DateTimeOriginal"] = re.sub(r'\d{4}:\d{2}:\d{2}', r'\1-\2-\3', info["DateTimeOriginal"])
    #     logging.debug(f"fixed DateTimeOriginal: {info['DateTimeOriginal']} from {file_path}")
    
    return info



# ----------------------------------------------------------------------------
# will do hash of entire file, not just part of it, in case a version of the
# file is corrupted and we then want to add the duplicate file to the catalog
def get_file_hash(filepath, block_size=65536):
    """Calculates the MD5 hash of a file."""
    hasher = hashlib.md5()
    try:
        with open(filepath, 'rb') as f:
            buf = f.read(block_size)
            while len(buf) > 0:
                hasher.update(buf)
                buf = f.read(block_size)
        return hasher.hexdigest()
    except IOError as e:
        logging.error(f"Could not read file {filepath} for hashing: {e}")
        return None

def get_file_datetime_from_exif(filepath):
      
    utc = 0     
    try:
        tags = extract_exif( filepath)
        if tags.get("DateTimeOriginal"):
            utc = UTC_from_exif( tags["DateTimeOriginal"], tags.get("OffsetTimeOriginal", "00:00"))
        else:
            utc = get_file_ctime( filepath)

    except Exception as e:
        logging.error(f"Error extracting EXIF data: {e}")
        utc = get_file_ctime( filepath)
    return utc


def organize_media(source_dir, dest_base_dir, delete_source_duplicates=False, dry_run=False, copy_mode=False):
    """
    Organizes photos and videos from source_dir to dest_base_dir.
    Can copy or move files. File extension checks are case-insensitive.
    """
    if not os.path.isdir(source_dir):
        logging.error(f"Source directory '{source_dir}' not found or is not a directory.")
        return
    if not os.path.isdir(dest_base_dir): # Check before creating
        try:
            if not dry_run:
                os.makedirs(dest_base_dir, exist_ok=True)
            logging.info(f"{'[DRY RUN] Would create' if dry_run else 'Created'} destination base directory: {dest_base_dir}")
        except OSError as e:
            logging.error(f"Could not create destination base directory '{dest_base_dir}': {e}")
            return

    processed_file_hashes = set() 
    
    if not dry_run:
        # if millions of files are processed, this can take a while
        # also RAM usage could be high and potentially cause issues
        logging.info("Scanning destination directory for existing file hashes...")
        hash_count = 0
        for root, _, files in os.walk(dest_base_dir):
            for filename in files:
                # Case-insensitive extension check
                if filename.lower().endswith(ALL_EXTENSIONS):
                    existing_file_path = os.path.join(root, filename)
                    existing_hash = get_file_hash(existing_file_path)
                    if existing_hash:
                        processed_file_hashes.add(existing_hash)
                        # print count of hashes added over itself
                        hash_count += 1  # probs faster than len(processed_file_hashes)
                        print(f"Hashes added: {hash_count}", end="\r", flush=True)                        
        logging.info(f"Found {len(processed_file_hashes)} existing unique files in destination.")
    print( "")  # Clear the line after the progress print

    files_processed = 0
    files_transferred = 0 # Renamed from files_moved
    files_skipped_duplicates = 0
    files_renamed = 0
    files_errored = 0
    dups_removed = 0 

    # Determine file operation based on copy_mode
    action_verb = "copy" if copy_mode else "move"
    action_gerund = "Copying" if copy_mode else "Moving"
    # uses shutil.copy2 when the --copy flag is active. 
    # shutil.copy2 is used because it attempts to preserve file metadata 
    # (like timestamps) during the copy, which is generally desirable for photos and videos.
    file_operation_func = shutil.copy2 if copy_mode else shutil.move

    logging.info(f"Scanning source directory: {source_dir}")
    for root, _, files in os.walk(source_dir):
        for item_name in files:
            source_filepath = os.path.join(root, item_name)

            if not os.path.isfile(source_filepath):
                logging.debug(f"Skipping non-file item: {item_name}")
                continue

            # Case-insensitive extension check
            if not item_name.lower().endswith(ALL_EXTENSIONS):
                logging.debug(f"Skipping file with unsupported extension (case-insensitive check): {item_name}")
                continue

            files_processed += 1
            logging.info(f"Processing ({files_processed}): {source_filepath}")

            file_dt = get_file_datetime_from_exif(source_filepath)
            logging.info( f"File date from EXIF or creation time: {file_dt}")
            if not file_dt:
                logging.error(f"Could not determine date for {source_filepath}. Skipping.")
                files_errored += 1
                continue

            day_folder_name = file_dt.split(' ')[0]
            year_str,month_str,day_str = day_folder_name.split('-')
            target_day_dir = os.path.join( dest_base_dir, year_str, day_folder_name)

            source_file_hash = get_file_hash(source_filepath)
            if not source_file_hash:
                logging.error(f"Could not calculate hash for {source_filepath}. Skipping.")
                files_errored += 1
                continue

            if source_file_hash in processed_file_hashes:
                logging.info(f"Exact duplicate of an already processed file (hash: {source_file_hash}). Skipping: {source_filepath}")
                files_skipped_duplicates += 1
                if delete_source_duplicates and not dry_run:
                    try:
                        os.remove(source_filepath)
                        dups_removed += 1
                        logging.info(f"Deleted duplicate source file: {source_filepath}")
                    except OSError as e:
                        logging.error(f"Could not delete duplicate source file {source_filepath}: {e}")
                continue

            original_filename = os.path.basename(source_filepath)  # This preserves original case
            current_target_filename = original_filename
            target_filepath = os.path.join(target_day_dir, current_target_filename)

            name_collision_counter = 1
            while os.path.exists(target_filepath):
                existing_target_hash = get_file_hash(target_filepath)
                if existing_target_hash == source_file_hash:
                    logging.info(f"Exact duplicate of file already in target location {target_filepath}. Skipping source.")
                    files_skipped_duplicates += 1
                    if delete_source_duplicates and not dry_run:
                        try:
                            os.remove(source_filepath)
                            logging.info(f"Deleted duplicate source file: {source_filepath}")
                        except OSError as e:
                            logging.error(f"Could not delete duplicate source file {source_filepath}: {e}")
                    source_filepath = None
                    break
                else:
                    name, ext = os.path.splitext(original_filename)
                    current_target_filename = f"{name}_{name_collision_counter}{ext}"
                    target_filepath = os.path.join(target_day_dir, current_target_filename)
                    logging.info(f"Name collision for {original_filename} in {target_day_dir}. Trying new name: {current_target_filename}")
                    if name_collision_counter == 1:
                        files_renamed += 1
                    name_collision_counter += 1

            if source_filepath is None:
                continue

            if not os.path.exists(target_day_dir):
                if not dry_run:
                    try:
                        os.makedirs(target_day_dir, exist_ok=True)
                        logging.info(f"Created directory: {target_day_dir}")
                    except OSError as e:
                        logging.error(f"Could not create directory {target_day_dir}: {e}")
                        files_errored += 1
                        continue
                else:
                    logging.info(f"[DRY RUN] Would create directory: {target_day_dir}")
            elif os.path.exists(target_day_dir) and not os.path.isdir(target_day_dir):
                logging.error(f"Target path {target_day_dir} exists but is not a directory. Skipping file {source_filepath}")
                files_errored += 1
                continue

            logging.info(f"{'[DRY RUN] Would ' + action_verb if dry_run else action_gerund} '{source_filepath}' to '{target_filepath}'")
            if not dry_run:
                try:
                    file_operation_func(source_filepath, target_filepath)  # Use selected operation
                    processed_file_hashes.add(source_file_hash)
                    files_transferred += 1
                except Exception as e:
                    logging.error(f"Could not {action_verb} {source_filepath} to {target_filepath}: {e}")
                    files_errored += 1
                    continue
            else:
                processed_file_hashes.add(source_file_hash)
                files_transferred += 1
 
 
    # Remove empty directories in source_dir if requested
    if delete_source_duplicates and not dry_run:
        for dirpath, dirnames, filenames in os.walk(source_dir, topdown=False):
            # Only remove if directory is empty (no files and no subdirs)
            if not dirnames and not filenames:
                try:
                    os.rmdir(dirpath)
                    logging.info(f"Removed empty directory: {dirpath}")
                except Exception as e:
                    logging.warning(f"Could not remove directory {dirpath}: {e}")

    logging.info("--- Organization Summary ---")
    logging.info(f"Total files scanned in source: {files_processed}")
    action_past_tense = "copied" if copy_mode else "moved"
    if dry_run:
        logging.info(f"Files that would be {action_past_tense}: {files_transferred}")
    else:
        logging.info(f"Files successfully {action_past_tense}: {files_transferred}")
    
    logging.info(f"Files skipped (exact duplicates): {files_skipped_duplicates}")
    logging.info(f"Files renamed due to name collision (different content): {files_renamed}")
    logging.info(f"File duplicates removed from source: {dups_removed}")
    logging.info(f"Files with errors: {files_errored}")
    logging.info("---------------------------")

# ----------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Organize photos and videos into YYYY/MM/YYYY-MM-DD directories. "
                    "Uses piexif for EXIF. Can move (default) or copy files."
    )
    parser.add_argument("source_dir", help="Directory containing the files to organize.")
    parser.add_argument("dest_base_dir", help="Base directory where organized files will be stored.")
    parser.add_argument(
        "--copy",
        action="store_true",
        help="Copy files instead of moving them. Preserves metadata."
    )
    parser.add_argument(
        "--delete-source-duplicates",
        action="store_true",
        help="Delete source files if they are found to be exact duplicates of already processed/target files. "
             "Use with caution, especially with --copy."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Simulate the organization process without changing any files."
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
    
    if args.copy and args.delete_source_duplicates:
        logging.warning("Using --copy with --delete-source-duplicates. Source files identified as duplicates will be deleted after successful copy of other files.")


    organize_media(
        args.source_dir, 
        args.dest_base_dir, 
        args.delete_source_duplicates, 
        args.dry_run, 
        args.copy # Pass the copy_mode flag
    )

    if args.dry_run:
        logging.info("*** DRY RUN finished. ***")

# ----------------------------------------------------------------------------

if __name__ == "__main__":
    main()
