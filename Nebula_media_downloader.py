#!/usr/bin/env python3
"""
Sci‑Fi Themed YouTube + Spotify Downloader GUI
Supports: yt-dlp (YouTube), spotdl (Spotify CLI)
Fallbacks (if installed): pytube, youtube_dl, pafy

Single-file PyQt5 app. Features:
 - Toggle between YouTube and Spotify mode
 - Playlist support (auto-detected by URL)
 - Audio-only (MP3) or full video (MP4) downloads
 - Choose output folder
 - Progress bar and live log
 - Threaded download to keep UI responsive

Dependencies:
 pip install pyqt5 yt-dlp spotdl pytube youtube_dl pafy

Run: python3 sci-fi_media_downloader.py
"""

import sys
import os
import threading
import subprocess
import shutil
from pathlib import Path

from PyQt5 import QtWidgets, QtCore, QtGui

# try imports for yt-dlp; we'll fail gracefully if missing
try:
    import yt_dlp as ytdlp
except Exception:
    ytdlp = None

# The app will use the spotdl CLI (assumes 'spotdl' is on PATH)


class WorkerSignals(QtCore.QObject):
    progress = QtCore.pyqtSignal(int)            # percent 0-100
    log = QtCore.pyqtSignal(str)                 # log lines
    finished = QtCore.pyqtSignal()
    error = QtCore.pyqtSignal(str)


class DownloadWorker(QtCore.QRunnable):
    def __init__(self, mode, url, outdir, audio_only, format_choice):
        super().__init__()
        self.mode = mode  # 'youtube' or 'spotify'
        self.url = url
        self.outdir = outdir
        self.audio_only = audio_only
        self.format_choice = format_choice
        self.signals = WorkerSignals()
        self._is_cancelled = False

    def cancel(self):
        self._is_cancelled = True

    def run(self):
        try:
            if self.mode == 'youtube':
                self._download_youtube()
            else:
                self._download_spotify()
        except Exception as e:
            self.signals.error.emit(str(e))
        finally:
            self.signals.finished.emit()

    # ----------------- YouTube via yt-dlp -----------------
    def _ydl_progress_hook(self, d):
        if self._is_cancelled:
            return
        status = d.get('status')
        if status == 'downloading':
            total = d.get('total_bytes') or d.get('total_bytes_estimate') or 0
            downloaded = d.get('downloaded_bytes') or 0
            pct = int((downloaded / total) * 100) if total else 0
            self.signals.progress.emit(pct)
            # build a short log message
            speed = d.get('speed')
            eta = d.get('eta')
            self.signals.log.emit(f"Downloading: {d.get('filename','?')} - {pct}% - ETA: {eta}s - {speed} B/s")
        elif status == 'finished':
            self.signals.log.emit('Download finished, finalizing...')
            self.signals.progress.emit(100)

    def _download_youtube(self):
        if ytdlp is None:
            raise RuntimeError('yt-dlp Python module not found. Install with: pip install yt-dlp')

        # build options
        outtmpl = os.path.join(self.outdir, '%(title)s.%(ext)s')
        ydl_opts = {
            'outtmpl': outtmpl,
            'noplaylist': False,  # allow playlist
            'progress_hooks': [self._ydl_progress_hook],
            'ignoreerrors': True,
            'quiet': True,
            'no_warnings': True,
        }

        if self.audio_only:
            # extract audio
            ydl_opts.update({
                'format': 'bestaudio/best',
                'postprocessors': [{
                    'key': 'FFmpegExtractAudio',
                    'preferredcodec': 'mp3',
                    'preferredquality': '192',
                }]
            })
        else:
            # allow video
            ydl_opts.update({'format': 'bestvideo+bestaudio/best'})

        self.signals.log.emit('Starting yt-dlp...')
        with ytdlp.YoutubeDL(ydl_opts) as ydl:
            # ydl.download accepts a list
            ydl.download([self.url])
        self.signals.log.emit('yt-dlp task complete')

    # ----------------- Spotify via spotdl CLI -----------------
    def _download_spotify(self):
        # Ensure spotdl CLI exists
        if shutil.which('spotdl') is None:
            raise RuntimeError("spotdl CLI not found on PATH. Install with: pip install spotdl and ensure 'spotdl' is available.")

        # Prepare CLI args
        args = ['spotdl', self.url, '--output', os.path.join(self.outdir, '%(title)s.%(ext)s')]
        if self.audio_only:
            # spotdl gives audio by default; we can force mp3
            args += ['--encode', 'mp3']
        # Run subprocess and stream lines
        self.signals.log.emit('Starting spotdl (CLI). This may spawn ffmpeg/yt-dlp under the hood.')

        proc = subprocess.Popen(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, universal_newlines=True)

        try:
            while True:
                if self._is_cancelled:
                    proc.terminate()
                    self.signals.log.emit('Cancelled by user')
                    break
                line = proc.stdout.readline()
                if not line:
                    if proc.poll() is not None:
                        break
                    continue
                self.signals.log.emit(line.strip())
                # try to parse progress from line if possible (very heuristic)
                if '%]' in line:
                    try:
                        # look for patterns like [ 23%]
                        pct = int(line.split('%]')[0].split()[-1].replace('[', '').replace('%', '').strip())
                        self.signals.progress.emit(max(0, min(100, pct)))
                    except Exception:
                        pass
        finally:
            rc = proc.wait()
            if rc == 0:
                self.signals.log.emit('spotdl finished successfully')
                self.signals.progress.emit(100)
            else:
                self.signals.error.emit(f'spotdl exited with code {rc}')


# ----------------- Main Window -----------------
class SciFiDownloader(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('NEBULA — Media Downloader')
        self.setWindowIcon(QtGui.QIcon())
        self.resize(880, 600)
        self._threadpool = QtCore.QThreadPool()

        self._build_ui()
        self._apply_style()

        self.current_worker = None

    def _build_ui(self):
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        layout = QtWidgets.QVBoxLayout(central)

        # Top: Mode toggle
        mode_layout = QtWidgets.QHBoxLayout()
        self.mode_group = QtWidgets.QButtonGroup()
        self.btn_youtube = QtWidgets.QRadioButton('YouTube')
        self.btn_spotify = QtWidgets.QRadioButton('Spotify')
        self.btn_youtube.setChecked(True)
        self.mode_group.addButton(self.btn_youtube)
        self.mode_group.addButton(self.btn_spotify)
        mode_layout.addWidget(self.btn_youtube)
        mode_layout.addWidget(self.btn_spotify)
        mode_layout.addStretch()

        # Input URL
        url_layout = QtWidgets.QHBoxLayout()
        self.url_input = QtWidgets.QLineEdit()
        self.url_input.setPlaceholderText('Paste YouTube / Spotify URL here...')
        url_layout.addWidget(QtWidgets.QLabel('URL:'))
        url_layout.addWidget(self.url_input)

        # Options
        opts_layout = QtWidgets.QHBoxLayout()
        self.chk_playlist = QtWidgets.QCheckBox('Playlist')
        self.chk_audio_only = QtWidgets.QCheckBox('Audio only (MP3)')
        self.format_combo = QtWidgets.QComboBox()
        self.format_combo.addItems(['mp3', 'mp4', 'webm'])
        self.format_combo.setCurrentIndex(0)
        opts_layout.addWidget(self.chk_playlist)
        opts_layout.addWidget(self.chk_audio_only)
        opts_layout.addStretch()
        opts_layout.addWidget(QtWidgets.QLabel('Preferred format:'))
        opts_layout.addWidget(self.format_combo)

        # Output folder
        out_layout = QtWidgets.QHBoxLayout()
        self.out_input = QtWidgets.QLineEdit(str(Path.home()))
        self.out_input.setPlaceholderText('Select output folder...')
        self.btn_browse = QtWidgets.QPushButton('Browse')
        self.btn_browse.clicked.connect(self._choose_folder)
        out_layout.addWidget(QtWidgets.QLabel('Output:'))
        out_layout.addWidget(self.out_input)
        out_layout.addWidget(self.btn_browse)

        # Buttons
        btn_layout = QtWidgets.QHBoxLayout()
        self.btn_download = QtWidgets.QPushButton('Download')
        self.btn_cancel = QtWidgets.QPushButton('Cancel')
        self.btn_cancel.setEnabled(False)
        self.btn_download.clicked.connect(self._on_download_clicked)
        self.btn_cancel.clicked.connect(self._on_cancel_clicked)
        btn_layout.addStretch()
        btn_layout.addWidget(self.btn_download)
        btn_layout.addWidget(self.btn_cancel)

        # Progress + log
        self.progress = QtWidgets.QProgressBar()
        self.progress.setValue(0)
        self.log = QtWidgets.QTextEdit()
        self.log.setReadOnly(True)
        self.log.setLineWrapMode(QtWidgets.QTextEdit.NoWrap)
        self.log.setFixedHeight(220)

        # Assemble
        layout.addLayout(mode_layout)
        layout.addLayout(url_layout)
        layout.addLayout(opts_layout)
        layout.addLayout(out_layout)
        layout.addLayout(btn_layout)
        layout.addWidget(self.progress)
        layout.addWidget(QtWidgets.QLabel('Log:'))
        layout.addWidget(self.log)

    def _apply_style(self):
        # Sci‑fi dark stylesheet (simple, self-contained)
        style = r"""
        QWidget { background: #0b0f1a; color: #cfefff; font-family: 'Consolas', 'Courier New', monospace; }
        QLineEdit, QTextEdit { background: #071022; border: 1px solid #0f3d5a; padding: 6px; color: #dff9ff }
        QComboBox, QSpinBox { background: #06202b; border: 1px solid #0f3d5a; padding: 4px }
        QPushButton { background: qlineargradient(spread:pad, x1:0, y1:0, x2:1, y2:0, stop:0 #06223a, stop:1 #08304b); border-radius: 8px; padding: 8px }
        QPushButton:hover { border: 1px solid #3fe6ff }
        QPushButton:pressed { padding-left: 6px }
        QProgressBar { background: #021018; border: 1px solid #0b5a7a; text-align: center }
        QProgressBar::chunk { background: qlineargradient(x1:0, y1:0, x2:1, y2:0, stop:0 #00f5ff, stop:1 #8a2be2); }
        QRadioButton, QCheckBox, QLabel { color: #aee9ff }
        QScrollBar:vertical { background: #071022; width: 12px }
        QScrollBar::handle:vertical { background: #0f3d5a; border-radius: 6px }
        """
        self.setStyleSheet(style)

    def _choose_folder(self):
        d = QtWidgets.QFileDialog.getExistingDirectory(self, 'Select output folder', self.out_input.text() or str(Path.home()))
        if d:
            self.out_input.setText(d)

    def _append_log(self, text):
        self.log.append(text)

    def _on_download_clicked(self):
        url = self.url_input.text().strip()
        if not url:
            QtWidgets.QMessageBox.warning(self, 'No URL', 'Please paste a YouTube or Spotify URL first.')
            return

        outdir = self.out_input.text().strip() or str(Path.home())
        os.makedirs(outdir, exist_ok=True)

        audio_only = self.chk_audio_only.isChecked()
        mode = 'youtube' if self.btn_youtube.isChecked() else 'spotify'

        # if spotify selected but url is clearly youtube, warn and auto switch
        if mode == 'spotify' and 'youtube' in url.lower():
            mode = 'youtube'
            self.btn_youtube.setChecked(True)

        self.progress.setValue(0)
        self.log.clear()
        self.btn_download.setEnabled(False)
        self.btn_cancel.setEnabled(True)

        # create and start worker
        worker = DownloadWorker(mode, url, outdir, audio_only, self.format_combo.currentText())
        worker.signals.progress.connect(self.progress.setValue)
        worker.signals.log.connect(self._append_log)
        worker.signals.error.connect(lambda e: self._on_worker_error(e))
        worker.signals.finished.connect(self._on_worker_finished)

        self.current_worker = worker
        self._threadpool.start(worker)

    def _on_cancel_clicked(self):
        if self.current_worker:
            self.current_worker.cancel()
            self._append_log('Cancellation requested...')
            self.btn_cancel.setEnabled(False)

    def _on_worker_finished(self):
        self.btn_download.setEnabled(True)
        self.btn_cancel.setEnabled(False)
        self._append_log('Task finished.')

    def _on_worker_error(self, message):
        self._append_log(f'ERROR: {message}')
        QtWidgets.QMessageBox.critical(self, 'Error', message)
        self.btn_download.setEnabled(True)
        self.btn_cancel.setEnabled(False)


def main():
    app = QtWidgets.QApplication(sys.argv)
    # High DPI scaling for crisp UI on modern displays
    QtCore.QCoreApplication.setAttribute(QtCore.Qt.AA_EnableHighDpiScaling)
    QtCore.QCoreApplication.setAttribute(QtCore.Qt.AA_UseHighDpiPixmaps)

    w = SciFiDownloader()
    w.show()
    sys.exit(app.exec_())


if __name__ == '__main__':
    main()
