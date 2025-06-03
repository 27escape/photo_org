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
import shutil
import hashlib
import argparse
import logging
from datetime import datetime
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

# Define which extensions are typically non-image/video for EXIF purposes if needed
# For piexif, we'll attempt EXIF on most non-video files.
VIDEO_EXTENSIONS = ('.avi', '.mp4', '.mov')


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

# --- Helper Functions ---
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

def get_file_datetime(filepath):
    """
    Tries to get the file creation datetime using piexif for EXIF data.
    Falls back to file system's modification time if EXIF is not available,
    unreadable, or for video files.
    Ensures all filepath operations are case-insensitive where appropriate.
    """
    file_ext_lower = os.path.splitext(filepath)[1].lower()

    # Attempt EXIF reading for non-video files
    if file_ext_lower not in VIDEO_EXTENSIONS:
        try:
            exif_dict = piexif.load(filepath)
            date_str_bytes = None
            
            # Preferred EXIF date tags using piexif constants
            preferred_tags = [
                piexif.ExifIFD.DateTimeOriginal,
                piexif.ExifIFD.DateTimeDigitized,
                piexif.ExifIFD.DateTime # General DateTime
            ]

            for tag in preferred_tags:
                if 'Exif' in exif_dict and tag in exif_dict['Exif']:
                    date_str_bytes = exif_dict['Exif'][tag]
                    break
                # Sometimes DateTime is in the '0th' IFD for some formats/cameras
                elif '0th' in exif_dict and tag in exif_dict['0th'] and tag == piexif.ExifIFD.DateTime : # only DateTime is common in 0th
                     date_str_bytes = exif_dict['0th'][tag]
                     break


            if date_str_bytes:
                exif_date_str = date_str_bytes.decode('utf-8').strip()
                # Common EXIF date format: 'YYYY:MM:DD HH:MM:SS'
                try:
                    return datetime.strptime(exif_date_str, '%Y:%m:%d %H:%M:%S')
                except ValueError:
                    try:
                        # Attempt to parse just the date part if time is malformed or missing
                        return datetime.strptime(exif_date_str.split(' ')[0], '%Y:%m:%d')
                    except ValueError:
                        logging.warning(f"Could not parse EXIF date string '{exif_date_str}' from {filepath} using piexif. Trying file timestamp.")
            else:
                logging.debug(f"No suitable EXIF date tag found for {filepath} using piexif. Using file timestamp.")

        except piexif.InvalidImageDataError: # piexif specific error for non-EXIF/corrupt
            logging.warning(f"piexif could not read EXIF data (InvalidImageDataError) for {filepath}. Using file timestamp.")
        except IOError as e:
            logging.warning(f"IOError opening {filepath} for piexif EXIF: {e}. Using file timestamp.")
        except Exception as e:
            logging.warning(f"Generic error reading EXIF with piexif for {filepath}: {e}. Using file timestamp.")
    else:
        logging.debug(f"File {filepath} is a video. Using file timestamp.")

    # Fallback to file modification time
    try:
        stat_info = os.stat(filepath)
        return datetime.fromtimestamp(stat_info.st_mtime)
    except OSError as e:
        logging.error(f"Could not get file timestamp for {filepath}: {e}")
        return None


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
        logging.info("Scanning destination directory for existing file hashes...")
        for root, _, files in os.walk(dest_base_dir):
            for filename in files:
                # Case-insensitive extension check
                if filename.lower().endswith(ALL_EXTENSIONS):
                    existing_file_path = os.path.join(root, filename)
                    existing_hash = get_file_hash(existing_file_path)
                    if existing_hash:
                        processed_file_hashes.add(existing_hash)
        logging.info(f"Found {len(processed_file_hashes)} existing unique files in destination.")


    files_processed = 0
    files_transferred = 0 # Renamed from files_moved
    files_skipped_duplicates = 0
    files_renamed = 0
    files_errored = 0

    # Determine file operation based on copy_mode
    action_verb = "copy" if copy_mode else "move"
    action_gerund = "Copying" if copy_mode else "Moving"
    # uses shutil.copy2 when the --copy flag is active. 
    # shutil.copy2 is used because it attempts to preserve file metadata 
    # (like timestamps) during the copy, which is generally desirable for photos and videos.
    file_operation_func = shutil.copy2 if copy_mode else shutil.move


    logging.info(f"Scanning source directory: {source_dir}")
    for item_name in os.listdir(source_dir):
        print( f"Processing item: {item_name}") # Debugging line to see what is being processed
        source_filepath = os.path.join(source_dir, item_name)

        if not os.path.isfile(source_filepath):
            logging.debug(f"Skipping non-file item: {item_name}")
            continue

        # Case-insensitive extension check
        if not item_name.lower().endswith(ALL_EXTENSIONS):
            logging.debug(f"Skipping file with unsupported extension (case-insensitive check): {item_name}")
            continue
        
        files_processed += 1
        logging.info(f"Processing ({files_processed}): {source_filepath}")

        file_dt = get_file_datetime(source_filepath)
        if not file_dt:
            logging.error(f"Could not determine date for {source_filepath}. Skipping.")
            files_errored += 1
            continue

        year_str = file_dt.strftime("%Y")
        month_str = file_dt.strftime("%m") 
        day_folder_name = file_dt.strftime("%Y-%m-%d")

        target_year_dir = os.path.join(dest_base_dir, year_str)
        target_month_dir = os.path.join(target_year_dir, month_str)
        target_day_dir = os.path.join(target_month_dir, day_folder_name)

        source_file_hash = get_file_hash(source_filepath)
        if not source_file_hash:
            logging.error(f"Could not calculate hash for {source_filepath}. Skipping.")
            files_errored +=1
            continue

        if source_file_hash in processed_file_hashes:
            logging.info(f"Exact duplicate of an already processed file (hash: {source_file_hash}). Skipping: {source_filepath}")
            files_skipped_duplicates += 1
            if delete_source_duplicates and not dry_run:
                try:
                    os.remove(source_filepath)
                    logging.info(f"Deleted duplicate source file: {source_filepath}")
                except OSError as e:
                    logging.error(f"Could not delete duplicate source file {source_filepath}: {e}")
            continue

        original_filename = os.path.basename(source_filepath) # This preserves original case
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
                    files_renamed +=1
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
             files_errored +=1
             continue

        logging.info(f"{'[DRY RUN] Would ' + action_verb if dry_run else action_gerund} '{source_filepath}' to '{target_filepath}'")
        if not dry_run:
            try:
                file_operation_func(source_filepath, target_filepath) # Use selected operation
                processed_file_hashes.add(source_file_hash) 
                files_transferred += 1
            except Exception as e:
                logging.error(f"Could not {action_verb} {source_filepath} to {target_filepath}: {e}")
                files_errored += 1
                continue
        else: 
            processed_file_hashes.add(source_file_hash) 
            files_transferred += 1


    logging.info("--- Organization Summary ---")
    logging.info(f"Total files scanned in source: {files_processed}")
    action_past_tense = "copied" if copy_mode else "moved"
    if dry_run:
        logging.info(f"Files that would be {action_past_tense}: {files_transferred}")
    else:
        logging.info(f"Files successfully {action_past_tense}: {files_transferred}")
    
    logging.info(f"Files skipped (exact duplicates): {files_skipped_duplicates}")
    logging.info(f"Files renamed due to name collision (different content): {files_renamed}")
    logging.info(f"Files with errors: {files_errored}")
    logging.info("---------------------------")


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

if __name__ == "__main__":
    main()
