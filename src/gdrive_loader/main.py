from urllib.parse import unquote
import requests
import argparse
import sys
from tqdm import tqdm
import os
import re
import threading
import math
import shutil
import json
from http.cookiejar import MozillaCookieJar
from requests.cookies import RequestsCookieJar
import tempfile

thread_errors = []

def load_cookies_from_file(cookies_file: str) -> RequestsCookieJar:
    """Load cookies from a Netscape cookies.txt or JSON export file."""
    if not os.path.exists(cookies_file):
        raise FileNotFoundError(f"Cookies file not found: {cookies_file}")

    with open(cookies_file, 'r') as f:
        content = f.read()

    stripped = content.lstrip()
    if stripped.startswith('[') or stripped.startswith('{'):
        try:
            data = json.loads(content)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON cookies file: {cookies_file}") from exc

        if isinstance(data, dict) and "cookies" in data and isinstance(data["cookies"], list):
            cookies_list = data["cookies"]
        elif isinstance(data, list):
            cookies_list = data
        else:
            raise ValueError(f"Unsupported JSON cookies format: {cookies_file}")

        jar = RequestsCookieJar()
        for cookie in cookies_list:
            if not isinstance(cookie, dict):
                continue
            name = cookie.get("name")
            value = cookie.get("value")
            domain = cookie.get("domain") or ""
            path = cookie.get("path") or "/"
            expires = cookie.get("expirationDate") or cookie.get("expires")
            if not name or value is None:
                continue
            jar.set(name, value, domain=domain, path=path, expires=expires)
        return jar

    generated_cookie_file = None
    if not stripped.startswith('# Netscape HTTP Cookie File') and not stripped.startswith('# HTTP Cookie File'):
        temp_file = tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False)
        temp_file.write('# Netscape HTTP Cookie File\n')
        temp_file.write('# https://curl.haxx.se/rfc/cookie_spec.html\n')
        temp_file.write('# This is a generated file! Do not edit.\n\n')
        temp_file.write(content)
        temp_file.close()
        generated_cookie_file = temp_file.name
        cookies_file = generated_cookie_file

    cookie_jar = MozillaCookieJar(cookies_file)
    try:
        cookie_jar.load(ignore_discard=True, ignore_expires=True)
    finally:
        if generated_cookie_file and os.path.exists(generated_cookie_file):
            os.remove(generated_cookie_file)

    requests_jar = RequestsCookieJar()
    for cookie in cookie_jar:
        requests_jar.set(
            cookie.name,
            cookie.value,
            domain=cookie.domain,
            path=cookie.path
        )

    return requests_jar

def get_cookies_session(cookies_file: str = None) -> requests.Session:
    """Create a requests session with optional cookies loaded from file."""
    session = requests.Session()

    if cookies_file:
        cookie_jar = load_cookies_from_file(cookies_file)
        session.cookies = cookie_jar

    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
        'Accept-Language': 'en-US,en;q=0.5',
    })

    return session

def extract_drive_id(input_str: str) -> str:
    """Extracts the Google Drive file ID from a URL or returns the input if it's already an ID."""
    pattern = r'/file/d/([a-zA-Z0-9_-]+)'
    match = re.search(pattern, input_str)
    if match:
        return match.group(1)
    return input_str

def get_video_url(page_content: str, verbose: bool) -> tuple[str, str]:
    """Extracts the video playback URL and title from the page content."""
    if verbose:
        print("[INFO] Parsing video playback URL and title.")
    contentList = page_content.split("&")
    video, title = None, None
    for content in contentList:
        if content.startswith('title=') and not title:
            title = unquote(content.split('=')[-1])
        elif "videoplayback" in content and not video:
            video = unquote(content).split("|")[-1]
        if video and title:
            break

    if verbose:
        print(f"[INFO] Video URL: {video}")
        print(f"[INFO] Video Title: {title}")

    return video, title

def get_file_size(url: str, session: requests.Session) -> int:
    """Gets the total file size via a HEAD request."""
    response = session.head(
        url,
        allow_redirects=True,
        headers={
            'Referer': 'https://drive.google.com/',
        }
    )
    return int(response.headers.get('content-length', 0))

def download_part(url: str, session: requests.Session, thread_lock, start: int, end: int, part_num: int, part_filename: str, chunk_size: int, pbar: tqdm, gpbar: tqdm, verbose: bool) -> None:
    """Downloads a specific byte range of the file and writes it to a part file."""
    headers = {
        'Range': f'bytes={start}-{end}',
        'Referer': 'https://drive.google.com/',
    }

    # Support resuming individual parts
    downloaded = 0
    if os.path.exists(part_filename):
        downloaded = os.path.getsize(part_filename)
        if downloaded > 0:
            headers['Range'] = f'bytes={start + downloaded}-{end}'

            # Update Progress
            with thread_lock:
                gpbar.update(downloaded)
                pbar.update(downloaded)
            
            if verbose:
                print(f"[INFO] Resuming part {part_filename} from byte {start + downloaded}")

    # Check Part already fully downloaded
    if downloaded >= (end - start + 1):
        return
        
    response = session.get(url, stream=True, headers=headers)
    if response.status_code not in (200, 206):
        raise Exception(f"[ERROR] Failed to download part {part_filename}, status: {response.status_code}")
    
    file_mode = 'ab' if os.path.exists(part_filename) and os.path.getsize(part_filename) > 0 else 'wb'
    with open(part_filename, file_mode) as f:
        for chunk in response.iter_content(chunk_size=chunk_size):
            f.write(chunk)
            with thread_lock:
                gpbar.update(len(chunk))
                pbar.update(len(chunk))
            downloaded += len(chunk)

            # Check Part fully downloaded
            if downloaded >= (end - start + 1):
                break

def download_part_wrapper(*args):
    try:
        download_part(*args)
    except Exception as e:
        print(e)
        thread_errors.append(e)

def merge_parts(part_files: list[str], output_filename: str, verbose: bool) -> None:
    """Merges all part files into the final output file."""
    if verbose:
        print(f"[INFO] Merging {len(part_files)} parts into {output_filename}")

    missing = [pf for pf in part_files if not os.path.exists(pf)]
    if missing:
        print(f"[ERROR] Missing parts: {missing}")
        return

    with open(output_filename, 'wb') as outfile:
        for part_file in part_files:
            if verbose:
                print("Merging " + part_file)
            with open(part_file, 'rb') as pf:
                shutil.copyfileobj(pf, outfile)
    
    for part_file in part_files: # Cleanup
        os.remove(part_file)

    if verbose:
        print(f"[INFO] Merge complete. Cleaned up part files.")

def download_file(url: str, session: requests.Session, filename: str, chunk_size: int, num_threads: int, verbose: bool) -> None:
    """Downloads the file using multiple threads, each handling a byte-range segment."""

    thread_errors.clear()
    num_threads = max(1, num_threads)

    total_size = get_file_size(url, session)
    if num_threads == 1:
        download_single_threaded(url, session, filename, chunk_size, verbose)
        return
    if total_size == 0:
        print("[WARN] Could not determine file size. Falling back to single-threaded download.")
        download_single_threaded(url, session, filename, chunk_size, verbose)
        return

    if verbose:
        print(f"[INFO] Total file size: {total_size} bytes")
        print(f"[INFO] Downloading with {num_threads} threads")

    part_size = math.ceil(total_size / num_threads)
    part_files = []
    threads = []

    gpBar = tqdm(
        unit='B', unit_scale=True,
        desc="Download Progress",
        total=total_size,
        position=0
    )

    pbars = [
        tqdm(
            unit='B', unit_scale=True,
            desc="Downloading Part " + str(i+1),
            total=min((i * part_size) + part_size - 1, total_size - 1) - (i * part_size) + 1,
            position=i+1
        )
        for i in range(num_threads)
    ]

    thread_lock = threading.Lock()

    for i in range(num_threads):
        start = i * part_size
        end = min(start + part_size - 1, total_size - 1)
        part_filename = f"{filename}.part{i}"
        part_files.append(part_filename)

        worker_session = requests.Session()
        worker_session.cookies.update(session.cookies)
        worker_session.headers.update(session.headers)

        t = threading.Thread(
            target=download_part_wrapper,
            args=(url, worker_session, thread_lock, start, end, i, part_filename, chunk_size, pbars[i], gpBar, verbose),
            daemon=True
        )
        threads.append(t)
        t.start()

    for t in threads:
        t.join()

    gpBar.close()
    for pbar in pbars:
        pbar.close()
    
    if(len(thread_errors) > 0):
        print(f"[ERROR] One of the parts failed. Check the console for details. Exiting...")
        return

    # Verify all parts downloaded correctly
    downloaded_total = sum(os.path.getsize(pf) for pf in part_files if os.path.exists(pf))
    if downloaded_total < total_size:
        print(f"[ERROR] Download incomplete: got {downloaded_total}/{total_size} bytes.")
        return
    

    merge_parts(part_files, filename, verbose)
    print(f"\n{filename} downloaded successfully.")

def download_single_threaded(url: str, session: requests.Session, filename: str, chunk_size: int, verbose: bool) -> None:
    """Fallback single-threaded download (original behavior)."""
    headers = {
        'Referer': 'https://drive.google.com/',
    }
    file_mode = 'wb'
    downloaded_size = 0

    if os.path.exists(filename):
        downloaded_size = os.path.getsize(filename)
        headers['Range'] = f"bytes={downloaded_size}-"
        file_mode = 'ab'

    if verbose:
        print(f"[INFO] Starting single-threaded download from {url}")

    response = session.get(url, stream=True, headers=headers)
    if response.status_code in (200, 206):  # 200 for new downloads, 206 for partial content
        total_size = int(response.headers.get('content-length', 0)) + downloaded_size
        with open(filename, file_mode) as file:
            with tqdm(total=total_size, initial=downloaded_size, unit='B', unit_scale=True, desc=filename, file=sys.stdout) as pbar:
                for chunk in response.iter_content(chunk_size=chunk_size):
                    if chunk:
                        file.write(chunk)
                        pbar.update(len(chunk))
        print(f"\n{filename} downloaded successfully.")
    else:
        print(f"Error downloading {filename}, status code: {response.status_code}")

def main_run(video_id_or_url: str, output_file: str = None, chunk_size: int = 1024, num_threads: int = 4, verbose: bool = False, cookies_file: str = None) -> None:
    """Main function to process video ID or URL and download the video file."""
    video_id = extract_drive_id(video_id_or_url)
    
    if verbose:
        print(f"[INFO] Extracted video ID: {video_id}")
        if cookies_file:
            print(f"[INFO] Using cookies from: {cookies_file}")

    try:
        session = get_cookies_session(cookies_file)
    except (FileNotFoundError, ValueError) as e:
        print(f"[ERROR] {e}")
        sys.exit(1)

    url = f"https://drive.google.com/get_video_info?docid={video_id}"
    response = session.get(url)

    if response.status_code != 200:
        print(f"[ERROR] Failed to fetch video info. Status code: {response.status_code}")
        return

    video_url, title = get_video_url(response.text, verbose)

    if not video_url:
        print("[ERROR] Could not extract video playback URL. Check if the video is accessible.")
        return

    if not output_file:
        output_file = f"{title}.mp4" if title else "video.mp4"

    download_file(video_url, session, output_file, chunk_size, num_threads, verbose)

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Download videos from Google Drive effortlessy, including view-only videos.")
    parser.add_argument("video_id", help="The video ID or Google Drive URL.")
    parser.add_argument("-o", "--output", help="Custom output filename.")
    parser.add_argument("-c", "--chunk_size", type=int, default=1024*1024, help="Chunk size for downloading (default: 1MB).")
    parser.add_argument("-t", "--threads", type=int, default=4, help="Number of threads for parallel downloading (default: 4).")
    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose logging.")
    parser.add_argument("--cookies", help="Path to cookies.txt or JSON cookies file.")
    parser.add_argument("--version", action="version", version="GDrive VideoLoader 1.1.0")

    args = parser.parse_args()
    main_run(args.video_id, args.output, args.chunk_size, args.threads, args.verbose, args.cookies)
