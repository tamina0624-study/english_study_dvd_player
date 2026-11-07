from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import time

from PySide6.QtCore import Qt, QTimer, QSize
from PySide6.QtGui import QColor, QImageReader, QIcon, QPixmap
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QFrame, QHBoxLayout, QLabel, QListWidget,
    QListWidgetItem, QMainWindow, QPushButton, QSlider,
    QSplitter, QTabWidget, QVBoxLayout, QWidget,
)

from dvd_player.core import CueIndex, SeekCoordinator, read_manifest, timestamp
from dvd_player.playback import Player, dvd_drives, media_identity


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("English DVD Player")
        self.resize(1200, 760)
        self.setMinimumSize(960, 600)
        self.engine = None
        self.loaded = False
        self.preparing = False
        self.ready = False
        self.media_id = ""
        self.title_id = 0
        self.generation = 0
        self.seek = SeekCoordinator()
        self.indexes = {"en": CueIndex(), "ja": CueIndex()}
        self.follow = True
        self.active_rows = None
        self.image_rows = {"en": set(), "ja": set()}
        self.highlight_rows = {"en": set(), "ja": set()}
        self.executor = ThreadPoolExecutor(max_workers=1)
        self.jobs = []
        self._build()
        self._refresh_drives()
        self.timer = QTimer(self)
        self.timer.setInterval(100)
        self.timer.timeout.connect(self._tick)
        self.timer.start()
        QTimer.singleShot(0, self._initialize)

    def _button(self, text, callback):
        button = QPushButton(text)
        button.clicked.connect(callback)
        return button

    def _build(self):
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        top = QHBoxLayout()
        self.drives = QComboBox()
        self.drives.setMinimumWidth(100)
        self.refresh = self._button("ドライブ再検索", self._refresh_drives)
        self.open_button = self._button("DVDを開く", self._open)
        self.titles = QComboBox()
        self.titles.setMinimumWidth(150)
        self.titles.activated.connect(self._select_title)
        for item in (QLabel("DVD"), self.drives, self.refresh, self.open_button,
                     QLabel("タイトル"), self.titles):
            top.addWidget(item)
        top.addStretch()
        layout.addLayout(top)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.video = QFrame()
        self.video.setStyleSheet("background:#080d14;border-radius:5px;")
        self.video.setAttribute(Qt.WidgetAttribute.WA_NativeWindow)
        splitter.addWidget(self.video)
        side = QWidget()
        side_layout = QVBoxLayout(side)
        self.tabs = QTabWidget()
        self.lists = {}
        for language, name in (("en", "英語"), ("ja", "日本語")):
            listing = QListWidget()
            listing.setIconSize(QSize(290, 130))
            listing.setWordWrap(True)
            listing.verticalScrollBar().sliderPressed.connect(self._manual_scroll)
            listing.viewport().installEventFilter(self)
            listing.setAccessibleName(name + "字幕一覧")
            self.lists[language] = listing
            self.tabs.addTab(listing, name)
        self.tabs.currentChanged.connect(self._language_changed)
        side_layout.addWidget(self.tabs)
        self.subtitle_status = QLabel("DVDを開いてください。")
        self.subtitle_status.setWordWrap(True)
        side_layout.addWidget(self.subtitle_status)
        self.import_button = self._button("事前処理した字幕を読み込む", self._import_subtitles)
        side_layout.addWidget(self.import_button)
        side_layout.addWidget(self._button("現在の字幕へ", self._enable_follow))
        splitter.addWidget(side)
        splitter.setSizes([780, 380])
        layout.addWidget(splitter, 1)
        controls = QHBoxLayout()
        self.previous = self._button("前チャプター", lambda: self._chapter(-1))
        self.rewind = self._button("↶ 2秒前に戻る", self._rewind)
        self.play_button = self._button("再生", self._toggle_play)
        self.stop_button = self._button("停止", self._stop)
        self.next = self._button("次チャプター", lambda: self._chapter(1))
        for button in (self.previous, self.rewind, self.play_button, self.stop_button, self.next):
            controls.addWidget(button)
        controls.addStretch()
        controls.addWidget(QLabel("音量"))
        self.volume = QSlider(Qt.Orientation.Horizontal)
        self.volume.setRange(0, 100)
        self.volume.setValue(70)
        self.volume.setMaximumWidth(150)
        self.volume.setAccessibleName("音量")
        self.volume.valueChanged.connect(self._volume_changed)
        controls.addWidget(self.volume)
        layout.addLayout(controls)
        timeline = QHBoxLayout()
        self.time_label = QLabel("--:-- / --:--")
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 10000)
        self.slider.setAccessibleName("再生位置")
        self.slider.sliderReleased.connect(self._seek_slider)
        timeline.addWidget(self.time_label)
        timeline.addWidget(self.slider, 1)
        layout.addLayout(timeline)
        self.statusBar().showMessage("初期化中…")
        self._set_controls(False)

    def eventFilter(self, obj, event):
        from PySide6.QtCore import QEvent
        if event.type() in (QEvent.Type.Wheel, QEvent.Type.KeyPress):
            self.follow = False
        return super().eventFilter(obj, event)

    def _manual_scroll(self):
        self.follow = False

    def _initialize(self):
        try:
            self.engine = Player(int(self.video.winId()))
            self.statusBar().showMessage("DVDを選択して「DVDを開く」を押してください。")
        except Exception:
            self.statusBar().showMessage("VLCを利用できません。Pythonと同じビット数のVLCを導入し、再起動してください。")
        self._set_controls(False)

    def _refresh_drives(self):
        selected = self.drives.currentText()
        self.drives.clear()
        self.drives.addItems(dvd_drives())
        if selected:
            self.drives.setCurrentText(selected)
        if not self.drives.count():
            self.statusBar().showMessage("DVDドライブが見つかりません。接続して再検索してください。")

    def _set_controls(self, available):
        for widget in (self.play_button, self.stop_button, self.titles):
            widget.setEnabled(available)
        seekable = bool(available and self.engine and self.engine.player.is_seekable())
        self.rewind.setEnabled(seekable)
        self.slider.setEnabled(seekable and self.engine.player.get_length() > 0)
        self.import_button.setEnabled(available and bool(self.media_id))
        self.open_button.setEnabled(self.engine is not None and not self.preparing)
        chapter = self.engine.player.get_chapter() if available else -1
        count = self.engine.player.get_chapter_count() if available else 0
        self.previous.setEnabled(available and chapter > 0)
        self.next.setEnabled(available and 0 <= chapter < count - 1)

    def _reset_subtitles(self):
        self.indexes = {"en": CueIndex(), "ja": CueIndex()}
        for listing in self.lists.values():
            listing.clear()
        self.active_rows = None
        self.image_rows = {"en": set(), "ja": set()}
        self.highlight_rows = {"en": set(), "ja": set()}
        self.follow = True

    def _open(self):
        if not self.engine or not self.drives.currentText():
            self._error("DVDドライブを選択してください。")
            return
        self.generation += 1
        self.loaded = self.ready = False
        self.preparing = True
        self.seek.clear()
        self.media_id = ""
        self.title_id = 0
        self.titles.clear()
        self._reset_subtitles()
        self.engine.player.stop()
        drive = self.drives.currentText()
        self.jobs.append(("identity", self.generation, self.executor.submit(media_identity, drive)))
        self.prepared_at = time.monotonic()
        self.statusBar().showMessage("DVD管理情報を読み込み中…")
        self.subtitle_status.setText("字幕を準備中…")
        self._set_controls(False)

    def _start_title(self):
        self.engine.open(self.drives.currentText(), self.title_id)
        self.engine.player.audio_set_volume(0)
        self.preparing = True
        self.prepared_at = time.monotonic()
        self.ready = False

    def _select_title(self, index):
        if not self.engine or index < 0:
            return
        self.generation += 1
        self.title_id = self.titles.itemData(index)
        self.seek.clear()
        self._reset_subtitles()
        try:
            self._start_title()
            self._set_controls(False)
        except Exception:
            self._playback_failed()

    def _finish_preparing(self):
        p = self.engine.player
        if self.titles.count() == 0:
            for i in range(max(1, p.get_title_count())):
                self.titles.addItem(f"タイトル {i + 1}", i)
        p.video_set_spu(-1)
        self.engine.pause()
        if p.is_seekable():
            self.engine.seek(0)
        p.audio_set_volume(self.volume.value())
        self.preparing = False
        self.ready = self.loaded = True
        self.subtitle_status.setText("DVD字幕の自動取得は未接続です。事前処理済み字幕（JSON＋画像）を読み込めます。")
        self.statusBar().showMessage(f"再生待機 ／ タイトル {self.title_id + 1}")

    def _toggle_play(self):
        if not self.ready:
            return
        try:
            playing = bool(self.engine.player.is_playing())
            if self.seek.target is not None:
                self.seek.resume = not self.seek.resume
                return
            self.engine.pause() if playing else self.engine.play()
        except Exception:
            self._playback_failed()

    def _stop(self):
        if not self.ready:
            return
        self.seek.clear()
        self.engine.pause()
        if self.engine.player.is_seekable():
            self.seek.request(0, False)
        else:
            self._start_title()

    def _rewind(self):
        if self.ready and self.engine.player.is_seekable():
            actual = self.engine.player.get_time()
            if actual >= 0:
                self.seek.rewind(actual, bool(self.engine.player.is_playing()))

    def _seek_slider(self):
        if self.ready and self.engine.player.is_seekable():
            duration = self.engine.player.get_length()
            if duration > 0:
                self.seek.request(duration * self.slider.value() // 10000,
                                  bool(self.engine.player.is_playing()))

    def _chapter(self, delta):
        if not self.ready:
            return
        p = self.engine.player
        target = p.get_chapter() + delta
        if 0 <= target < p.get_chapter_count():
            resume = self.seek.resume if self.seek.target is not None else bool(p.is_playing())
            self.seek.clear()
            p.set_chapter(target)
            self.engine.play() if resume else self.engine.pause()
            self.active_rows = None

    def _volume_changed(self, value):
        if self.engine and not self.preparing:
            self.engine.player.audio_set_volume(value)

    def _language_changed(self, _index):
        self.follow = True
        self.active_rows = None

    def _enable_follow(self):
        self.follow = True
        self.active_rows = None

    def _import_subtitles(self):
        filename, _ = QFileDialog.getOpenFileName(self, "字幕manifest.jsonを選択", "", "字幕情報 (*.json)")
        if filename:
            job = self.executor.submit(read_manifest, Path(filename), self.media_id, self.title_id)
            self.jobs.append(("subtitles", self.generation, job))
            self.subtitle_status.setText("字幕データを読み込み中…")

    def _apply_subtitles(self, result):
        index, language = result
        listing = self.lists[language]
        listing.clear()
        self.image_rows[language] = set()
        self.highlight_rows[language] = set()
        self.indexes[language] = index
        for cue in index.cues:
            item = QListWidgetItem(timestamp(cue.start_ms))
            item.setSizeHint(QSize(300, 80))
            item.setData(Qt.ItemDataRole.UserRole, False)
            listing.addItem(item)
        self.subtitle_status.setText("字幕データを読み込みました。画像は表示位置に応じて読み込みます。")
        self.active_rows = None

    def _load_visible_images(self, listing, index, language):
        # Load only visible rows; pixmaps outside the viewport are released.
        viewport = listing.viewport().rect()
        from PySide6.QtCore import QPoint
        first = listing.indexAt(QPoint(1, 1)).row()
        first = max(0, first)
        visible_rows = set()
        for i in range(first, min(listing.count(), first + 30)):
            if listing.visualItemRect(listing.item(i)).intersects(viewport):
                visible_rows.add(i)
        for i in visible_rows | self.image_rows[language]:
            item = listing.item(i)
            visible = i in visible_rows
            if visible and not item.data(Qt.ItemDataRole.UserRole):
                reader = QImageReader(str(index.cues[i].image))
                size = reader.size()
                if not size.isValid() or max(size.width(), size.height()) > 4096:
                    item.setText(timestamp(index.cues[i].start_ms) + "　画像を読み込めません")
                else:
                    reader.setScaledSize(size.scaled(QSize(290, 130), Qt.AspectRatioMode.KeepAspectRatio))
                    image = reader.read()
                    if not image.isNull():
                        item.setIcon(QIcon(QPixmap.fromImage(image)))
                    else:
                        item.setText(timestamp(index.cues[i].start_ms) + "　画像を読み込めません")
                item.setData(Qt.ItemDataRole.UserRole, True)
            elif not visible and item.data(Qt.ItemDataRole.UserRole):
                item.setIcon(QIcon())
                item.setData(Qt.ItemDataRole.UserRole, False)
        self.image_rows[language] = visible_rows

    def _sync(self, ms):
        language = "en" if self.tabs.currentIndex() == 0 else "ja"
        index, listing = self.indexes[language], self.lists[language]
        active = index.active(ms) if ms >= 0 else []
        key = (language, tuple(active))
        if key != self.active_rows:
            old_rows = self.highlight_rows[language]
            for i in set(old_rows) | set(active):
                listing.item(i).setBackground(QColor("#176b87") if i in active else QColor("transparent"))
                listing.item(i).setForeground(QColor("white") if i in active else self.palette().text())
            if self.follow and active:
                listing.scrollToItem(listing.item(active[0]))
            self.active_rows = key
            self.highlight_rows[language] = set(active)
        self._load_visible_images(listing, index, language)

    def _tick(self):
        for kind, generation, job in list(self.jobs):
            if not job.done():
                continue
            self.jobs.remove((kind, generation, job))
            if generation != self.generation:
                continue
            try:
                result = job.result()
                if kind == "identity":
                    self.media_id = result
                    self._start_title()
                else:
                    self._apply_subtitles(result)
            except Exception as error:
                if kind == "identity":
                    self.preparing = False
                    self._error("DVDを読み込めません。媒体とドライブを確認してください。")
                else:
                    self.subtitle_status.setText(str(error) if isinstance(error, ValueError) else "字幕を読み込めません。形式と画像を確認してください。")
        if not self.engine:
            return
        try:
            p = self.engine.player
            state = p.get_state()
            if self.preparing:
                if state == self.engine.vlc.State.Error or time.monotonic() - self.prepared_at > 20:
                    self._playback_failed()
                elif state in (self.engine.vlc.State.Playing, self.engine.vlc.State.Paused):
                    self._finish_preparing()
            elif self.ready:
                if state == self.engine.vlc.State.Error:
                    self._playback_failed()
                elif state == self.engine.vlc.State.Ended:
                    self._start_title()
                else:
                    self._update_playback()
            self._set_controls(self.ready)
        except Exception:
            self._playback_failed()

    def _update_playback(self):
        p = self.engine.player
        actual, duration = p.get_time(), p.get_length()
        pending = self.seek.target is not None
        try:
            command = self.seek.next_command(actual)
            if command is not None:
                self.engine.pause()
                self.engine.seek(command)
            elif pending and self.seek.target is None:
                if self.seek.resume:
                    self.engine.play()
        except (TimeoutError, RuntimeError) as error:
            resume = self.seek.resume
            self.seek.clear()
            if resume:
                self.engine.play()
            self.statusBar().showMessage(str(error), 6000)
        self.time_label.setText(f"{timestamp(actual)} / {timestamp(duration)}")
        if duration > 0 and actual >= 0 and not self.slider.isSliderDown():
            self.slider.setValue(min(10000, actual * 10000 // duration))
        self.play_button.setText("一時停止" if p.is_playing() else "再生")
        self._sync(actual)

    def _error(self, message):
        self.statusBar().showMessage(message)

    def _playback_failed(self):
        self.generation += 1
        self.ready = self.loaded = self.preparing = False
        self.seek.clear()
        self._reset_subtitles()
        if self.engine:
            self.engine.player.stop()
        self._set_controls(False)
        self._error("DVD再生に失敗しました。媒体・リージョン・VLCを確認して再度読み込んでください。")

    def closeEvent(self, event):
        self.generation += 1
        self.timer.stop()
        for _, _, job in self.jobs:
            job.cancel()
        self.executor.shutdown(wait=False, cancel_futures=True)
        if self.engine:
            self.engine.close()
        event.accept()
