# Enhanced GDrive Loader 🚀

A professional, high-performance Google Drive video downloader.

## ✨ Features
- **Parallel Downloading**: Uses multiple threads to saturate your bandwidth and speed up downloads.
- **View-Only Support**: Can download videos even if the "Download" button is disabled in Google Drive.
- **Resumable Downloads**: Supports resuming interrupted downloads for both single and multi-threaded modes.
- **Cookie Support**: Support for private videos via `cookies.txt` or JSON cookie exports.
- **Clean Structure**: Organized as a proper Python project for better maintainability.

## 📋 Prerequisites
- **Python 3.8 - 3.13**: [Download Python](https://www.python.org/downloads/)
- **Git**: [Download Git](https://git-scm.com/downloads)

## 🚀 Quick Start

### 1. Clone & Install
```bash
git clone https://github.com/AbdelrahmanMostafa-Eng/GoogleDrive-Downloader.git
```
```
cd GoogleDrive-Downloader
```
```
pip install -r requirements.txt
```

### 2. Run
```bash
python src/gdrive_loader/main.py "YOUR_GDRIVE_URL"
```

### ⚙️ Options
- `-o, --output`: Specify a custom output filename.
- `-t, --threads`: Number of threads for parallel downloading (default: 4).
- `-c, --chunk_size`: Custom chunk size in bytes (default: 1MB).
- `-v, --verbose`: Enable detailed logging.
- `--cookies`: Path to your cookies file for private videos.

## 🏗 Project Structure
```text
GoogleDrive-Downloader/
├── src/
│   └── gdrive_loader/
│       └── main.py       # Core logic and entry point
├── requirements.txt      # Project dependencies
└── README.md             # Project overview
```

## 📄 License
This project is licensed under the MIT License.
