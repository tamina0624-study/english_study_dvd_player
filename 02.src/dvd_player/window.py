from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import time
import queue
import threading

from PySide6.QtCore import Qt, QTimer, QSize
from PySide6.QtGui import QColor, QImageReader, QIcon, QPixmap, QFont
from PySide6.QtWidgets import (
    QComboBox, QFileDialog, QFrame, QHBoxLayout, QLabel, QListWidget, QInputDialog,
    QListWidgetItem, QMainWindow, QPushButton, QSlider,
    QSplitter, QStyle, QVBoxLayout, QWidget,
)

from dvd_player.core import CueIndex, SeekCoordinator, timestamp
from dvd_player.playback import Player, dvd_drives, dvd_name
from dvd_player.storage import CacheStore, app_data_dir, setup_logging, subtitle_data_dir
from dvd_player.extraction import DvdSubtitleExtractor, ExtractionCancelled, checked_identity, probe_media
from dvd_player.subtitle_edit import find_editor, export_for_editor, launch_editor
from dvd_player.theme import apply_theme, tint_icon, SubtitleDelegate, operation_icon


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("English DVD Player")
        self.resize(1450, 800)
        self.setMinimumSize(1100, 600)
        self.engine = None
        self.loaded = False
        self.preparing = False
        self.ready = False
        self.media_id = ""
        self.media_name = "DVD"
        self.loaded_drive = ""
        self.title_id = 0
        self.generation = 0
        self.cache = CacheStore(subtitle_data_dir())
        self.logger = setup_logging(app_data_dir())
        self.cache_loaded = None
        self.extraction_cancel = threading.Event()
        self.extracting = False
        self.extraction_events = queue.SimpleQueue()
        self.unknown_tracks = []
        self.media_cancel = threading.Event()
        self.media_executor = ThreadPoolExecutor(max_workers=1)
        self.last_media_check = time.monotonic()
        self.seek = SeekCoordinator()
        self.navigation_executor = ThreadPoolExecutor(max_workers=1)
        self.navigation_job = None
        self.navigation_kind = None
        self.navigation_started = 0
        self.navigation_reported = False
        self.indexes = {"en": CueIndex(), "ja": CueIndex()}
        self.tracks = {"en": [], "ja": []}
        self.selected_tracks = {"en": None, "ja": None}
        self.active_language = "en"
        self.follow = True
        self.active_rows = {"en": None, "ja": None}
        self.image_rows = set()
        self.highlight_rows = {"en": set(), "ja": set()}
        self.cue_rows = {"en": [], "ja": []}
        self.executor = ThreadPoolExecutor(max_workers=1)
        self.editor_executor = ThreadPoolExecutor(max_workers=1)
        self.editor_path = find_editor()
        self.srt_sources = {}
        self.jobs = []
        apply_theme(self)
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

    def _icon_button(self, icon, name, tooltip, callback):
        button = QPushButton()
        button.setIcon(operation_icon(name) or tint_icon(self.style().standardIcon(icon)))
        button.setIconSize(QSize(18, 18))
        button.setFixedSize(30, 30)
        button.setProperty("role", "icon")
        button.setToolTip(tooltip)
        button.setAccessibleName(name)
        button.clicked.connect(callback)
        return button

    def _build(self):
        root = QWidget()
        root.setObjectName("appRoot")
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(20, 12, 20, 6)
        layout.setSpacing(14)
        header = QHBoxLayout()
        header.setSpacing(12)
        mark = QLabel("▶")
        mark.setObjectName("brandMark")
        header.addWidget(mark)
        brand = QVBoxLayout()
        brand.setSpacing(1)
        title = QLabel("DVD STUDY")
        title.setObjectName("brandTitle")
        subtitle = QLabel("見て、戻って、理解する。")
        subtitle.setObjectName("brandSubtitle")
        brand.addWidget(title)
        brand.addWidget(subtitle)
        header.addLayout(brand)
        header.addStretch()
        badge = QLabel("EN  /  日本語")
        badge.setObjectName("languageBadge")
        header.addWidget(badge)
        layout.addLayout(header)
        source_bar = QFrame()
        source_bar.setObjectName("sourceBar")
        top = QHBoxLayout(source_bar)
        top.setContentsMargins(14, 10, 14, 10)
        top.setSpacing(10)
        self.drives = QComboBox()
        self.drives.setMinimumWidth(100)
        self.refresh = self._button("ドライブ再検索", self._refresh_drives)
        self.open_button = self._button("DVDを開く", self._open)
        self.open_button.setProperty("role", "primary")
        self.folder_button = self._button("DVDフォルダを開く", self._open_folder)
        self.titles = QComboBox()
        self.titles.setMinimumWidth(150)
        self.titles.activated.connect(self._select_title)
        for item in (QLabel("DVD"), self.drives, self.refresh, self.open_button, self.folder_button,
                     QLabel("タイトル"), self.titles):
            top.addWidget(item)
        top.addStretch()
        layout.addWidget(source_bar)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.setChildrenCollapsible(False)
        splitter.setHandleWidth(14)
        video_card = QFrame()
        video_card.setObjectName("videoCard")
        video_card.setMinimumWidth(420)
        video_layout = QVBoxLayout(video_card)
        video_layout.setContentsMargins(12, 12, 12, 12)
        video_layout.setSpacing(10)
        video_heading = QLabel("映像")
        video_heading.setObjectName("sectionTitle")
        video_layout.addWidget(video_heading)
        self.video = QFrame()
        self.video.setObjectName("videoSurface")
        self.video.setAttribute(Qt.WidgetAttribute.WA_NativeWindow)
        video_layout.addWidget(self.video, 1)
        splitter.addWidget(video_card)
        side = QFrame()
        side.setObjectName("subtitleCard")
        side.setMinimumWidth(360)
        side_layout = QVBoxLayout(side)
        side_layout.setContentsMargins(14, 12, 14, 8)
        side_layout.setSpacing(7)
        subtitle_header = QHBoxLayout()
        subtitle_heading = QLabel("字幕")
        subtitle_heading.setObjectName("sectionTitle")
        subtitle_header.addWidget(subtitle_heading)
        subtitle_header.addStretch()
        subtitle_hint = QLabel("英語・日本語を時間順に")
        subtitle_hint.setObjectName("sectionHint")
        subtitle_header.addWidget(subtitle_hint)
        side_layout.addLayout(subtitle_header)
        listing = QListWidget()
        listing.setItemDelegate(SubtitleDelegate(listing))
        listing.setResizeMode(QListWidget.ResizeMode.Adjust)
        listing.setIconSize(QSize(600, 64))
        listing.setWordWrap(True)
        listing.verticalScrollBar().sliderPressed.connect(self._manual_scroll)
        listing.viewport().installEventFilter(self)
        listing.itemClicked.connect(self._select_subtitle_item)
        listing.setAccessibleName("英語・日本語字幕一覧")
        self.subtitle_list = listing
        side_layout.addWidget(listing, 1)
        self.subtitle_status = QLabel("DVDを開いてください。")
        self.subtitle_status.setObjectName("subtitleStatus")
        self.subtitle_status.setWordWrap(True)
        side_layout.addWidget(self.subtitle_status)
        self.import_button = self._icon_button(
            QStyle.StandardPixmap.SP_DialogOpenButton, "字幕を読み込む",
            "SRTまたは字幕JSONを読み込みます。初期言語は最後に選択した字幕の言語です。",
            self._import_subtitles)
        self.ocr_button = self._icon_button(
            QStyle.StandardPixmap.SP_FileDialogInfoView, "Subtitle EditでOCR",
            "選択中の言語の画像字幕をSubtitle Edit用に書き出して開きます。", self._auto_ocr)
        self.edit_button = self._icon_button(
            QStyle.StandardPixmap.SP_FileDialogDetailedView, "Subtitle Editで編集",
            "選択中の言語の字幕をSubtitle Editで編集します。", self._open_editor)
        subtitle_menu = self.menuBar().addMenu("字幕")
        self.reload_srt_action = subtitle_menu.addAction("編集したSRTを再読み込み")
        self.reload_srt_action.triggered.connect(self._reload_srt)
        self.track_menus = {
            "en": subtitle_menu.addMenu("英語字幕トラック"),
            "ja": subtitle_menu.addMenu("日本語字幕トラック"),
        }
        self.extract_button = self._icon_button(
            QStyle.StandardPixmap.SP_BrowserReload, "DVD字幕を取得",
            "DVDから英語・日本語の字幕を取得または再取得します。", self._start_extraction)
        self.cancel_extract_button = self._icon_button(
            QStyle.StandardPixmap.SP_BrowserStop, "字幕取得を中止",
            "実行中のDVD字幕取得を中止します。", self._stop_extraction)
        self.assign_language_button = self._icon_button(
            QStyle.StandardPixmap.SP_DialogApplyButton, "言語不明トラックを指定",
            "言語を判別できなかったDVD字幕に英語または日本語を割り当てます。",
            self._assign_language)
        self.coverage_status = QLabel("")
        self.coverage_status.setObjectName("coverageStatus")
        self.follow_button = self._icon_button(
            QStyle.StandardPixmap.SP_ArrowDown, "現在の字幕へ追従",
            "英語・日本語の字幕一覧を再生位置へ追従させます。", self._enable_follow)
        self.follow_button.setCheckable(True)
        self.follow_button.setChecked(self.follow)
        side_layout.addWidget(self.coverage_status)
        splitter.addWidget(side)
        splitter.setSizes([760, 640])
        layout.addWidget(splitter, 1)
        transport = QFrame()
        transport.setObjectName("transportBar")
        controls = QHBoxLayout(transport)
        controls.setContentsMargins(12, 10, 12, 10)
        controls.setSpacing(8)
        self.previous = self._button("前チャプター", lambda: self._chapter(-1))
        self.rewind = self._button("↶ 2秒前に戻る", self._rewind)
        self.play_button = self._button("再生", self._toggle_play)
        self.play_button.setProperty("role", "primary")
        self.play_button.setMinimumWidth(76)
        self.play_button.setIcon(tint_icon(self.style().standardIcon(QStyle.StandardPixmap.SP_MediaPlay), "#10252a"))
        self.stop_button = self._button("停止", self._stop)
        self.next = self._button("次チャプター", lambda: self._chapter(1))
        for button in (self.previous, self.rewind, self.play_button, self.stop_button, self.next):
            controls.addWidget(button)
        for button in (self.import_button, self.extract_button, self.ocr_button,
                       self.edit_button, self.cancel_extract_button,
                       self.assign_language_button, self.follow_button):
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
        layout.addWidget(transport)
        timeline = QHBoxLayout()
        timeline.setContentsMargins(5, 0, 5, 2)
        timeline.setSpacing(16)
        self.time_label = QLabel("--:-- / --:--")
        self.time_label.setObjectName("timeDisplay")
        self.time_label.setMinimumWidth(130)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 10000)
        self.slider.setAccessibleName("再生位置")
        self.slider.sliderReleased.connect(self._seek_slider)
        self.slider.actionTriggered.connect(self._slider_action)
        timeline.addWidget(self.time_label)
        timeline.addWidget(self.slider, 1)
        layout.addLayout(timeline)
        self.statusBar().showMessage("初期化中…")
        self._set_controls(False)

    def eventFilter(self, obj, event):
        from PySide6.QtCore import QEvent
        if obj is self.subtitle_list.viewport() and event.type() == QEvent.Type.MouseButtonPress:
            item = self.subtitle_list.itemAt(event.position().toPoint())
            if item:
                metadata = item.data(Qt.ItemDataRole.UserRole)
                self.active_language = metadata[0]
        if event.type() in (QEvent.Type.Wheel, QEvent.Type.KeyPress):
            self._manual_scroll()
        return super().eventFilter(obj, event)

    def _select_subtitle_item(self, item):
        metadata = item.data(Qt.ItemDataRole.UserRole)
        if metadata:
            self.active_language = metadata[0]

    def _manual_scroll(self):
        self.follow = False
        self.follow_button.setChecked(False)
        self.follow_button.setToolTip("自動スクロール停止中。クリックすると現在の字幕へ追従します。")

    def _initialize(self):
        try:
            self.engine = Player(int(self.video.winId()))
            self.statusBar().showMessage("DVDを選択して「DVDを開く」を押してください。" if self.drives.count()
                                        else "VLCの準備ができました。DVDドライブを接続して再検索してください。")
        except Exception:
            self.logger.warning("ENV_MISSING operation=initialize")
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
        self.ocr_button.setEnabled(available and bool(self.media_id))
        self.edit_button.setEnabled(available and bool(self.media_id))
        self.reload_srt_action.setEnabled(available)
        self.extract_button.setEnabled(available and bool(self.media_id) and not self.extracting)
        self.cancel_extract_button.setEnabled(self.extracting)
        self.assign_language_button.setEnabled(available and bool(self.unknown_tracks))
        self.open_button.setEnabled(self.engine is not None and not self.preparing and self.navigation_job is None)
        self.folder_button.setEnabled(self.engine is not None and not self.preparing and self.navigation_job is None)
        self.volume.setEnabled(self.navigation_job is None)
        chapter = self.engine.player.get_chapter() if available else -1
        count = self.engine.player.get_chapter_count() if available else 0
        self.previous.setEnabled(available and chapter > 0)
        self.next.setEnabled(available and 0 <= chapter < count - 1)

    def _reset_subtitles(self):
        self.indexes = {"en": CueIndex(), "ja": CueIndex()}
        self.tracks = {"en": [], "ja": []}
        self.selected_tracks = {"en": None, "ja": None}
        self.subtitle_list.clear()
        for menu in self.track_menus.values():
            menu.clear()
        self.cache_loaded = None
        self.unknown_tracks = []
        self.coverage_status.clear()
        self.active_rows = {"en": None, "ja": None}
        self.image_rows = set()
        self.highlight_rows = {"en": set(), "ja": set()}
        self.cue_rows = {"en": [], "ja": []}
        self.follow = True

    def _open(self):
        if not self.engine or not self.drives.currentText():
            self._error("DVDドライブを選択してください。")
            return
        self._open_source(self.drives.currentText())

    def _open_folder(self):
        source = QFileDialog.getExistingDirectory(self, "VIDEO_TSを含むDVDフォルダを選択")
        if source:
            directory = Path(source)
            if directory.name.upper() == "VIDEO_TS":
                directory = directory.parent
            self._open_source(str(directory))

    def _open_source(self, source):
        if not self.engine or self.navigation_job is not None:
            return
        self._cancel_extraction()
        self.media_cancel.set()
        self.media_cancel = threading.Event()
        self.generation += 1
        self.loaded = self.ready = False
        self.preparing = True
        self.seek.clear()
        self.media_id = ""
        self.media_name = dvd_name(source)
        self.title_id = 0
        self.titles.clear()
        self._reset_subtitles()
        self._begin_navigation("stop", self.engine.player.stop)
        drive = source
        self.loaded_drive = drive
        self.jobs.append(("identity", self.generation,
                          self.media_executor.submit(checked_identity, drive, self.media_cancel)))
        self.prepared_at = time.monotonic()
        self.statusBar().showMessage("DVD管理情報を読み込み中…")
        self.subtitle_status.setText("字幕を準備中…")
        self._set_controls(False)

    def _start_title(self):
        self.seek.clear()
        self.preparing = True
        self.prepared_at = time.monotonic()
        self._begin_navigation("open", self.engine.open, self.loaded_drive, self.title_id, volume=0)

    def _select_title(self, index):
        if not self.engine or index < 0 or self.navigation_job is not None:
            return
        self._cancel_extraction()
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
        self._begin_navigation("prepare", self.engine.prepare, self.volume.value(), self.titles.count() == 0)

    def _complete_preparing(self, titles):
        for title_id, duration in titles:
            self.titles.addItem(f"タイトル {title_id + 1} ({timestamp(duration)})", title_id)
        self.preparing = False
        self.ready = self.loaded = True
        self.subtitle_status.setText("保存済み字幕を確認しています…")
        self.statusBar().showMessage(f"再生待機 ／ タイトル {self.title_id + 1}")
        cache_key = (self.media_id, self.title_id)
        if self.media_id and self.cache_loaded != cache_key:
            self.cache_loaded = cache_key
            self.jobs.append(("cache", self.generation, self.executor.submit(
                self.cache.load_tracks, self.media_id, self.title_id)))

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

    def _slider_action(self, _action):
        if not self.slider.isSliderDown():
            QTimer.singleShot(0, self._seek_slider)

    def _chapter(self, delta):
        if not self.ready or self.navigation_job is not None:
            return
        resume = self.seek.resume if self.seek.target is not None else None
        self.seek.clear()
        self._begin_navigation("chapter", self.engine.change_chapter, delta, resume)
        self.statusBar().showMessage("チャプターを移動中…")

    def _begin_navigation(self, kind, function, *args, **kwargs):
        if self.navigation_job is not None:
            raise RuntimeError("DVD操作の完了を待ってください。")
        self.logger.info("NAVIGATION_BEGIN kind=%s title=%s", kind, self.title_id)
        self.ready = False
        self.navigation_kind = kind
        self.navigation_started = time.monotonic()
        self.navigation_reported = False
        self.navigation_job = self.navigation_executor.submit(function, *args, **kwargs)
        self._set_controls(False)

    def _volume_changed(self, value):
        if self.engine and not self.preparing and self.navigation_job is None:
            self.engine.player.audio_set_volume(value)

    def _enable_follow(self):
        self.follow = True
        self.follow_button.setChecked(True)
        self.follow_button.setToolTip("自動スクロール中。字幕一覧を手動でスクロールすると停止します。")
        self.active_rows = {"en": None, "ja": None}
        rows = self.highlight_rows["en"] | self.highlight_rows["ja"]
        if rows:
            self.subtitle_list.scrollToItem(self.subtitle_list.item(min(rows)),
                                           QListWidget.ScrollHint.PositionAtCenter)

    def _import_subtitles(self):
        language = self.active_language
        suggested = self.srt_sources.get((self.media_id, self.title_id, language), "")
        filename, _ = QFileDialog.getOpenFileName(self, "現在のDVDタイトル用の字幕を選択", str(suggested),
                                                "字幕 (*.srt *.json);;SubRip (*.srt);;画像字幕 (*.json)")
        if filename:
            if Path(filename).suffix.lower() == ".srt":
                name, accepted = QInputDialog.getItem(self, "SRTの言語",
                    f"タイトル {self.title_id + 1} の字幕として読み込む言語", ["英語", "日本語"],
                    current=0 if language == "en" else 1, editable=False)
                if not accepted:
                    return
                language = "en" if name == "英語" else "ja"
                self._queue_srt(Path(filename), language)
                return
            job = self.editor_executor.submit(self.cache.import_manifest, Path(filename), self.media_id, self.title_id)
            self.jobs.append(("subtitles", self.generation, job))
            self.subtitle_status.setText("字幕データを読み込み中…")

    def _queue_srt(self, source, language):
        self.srt_sources[(self.media_id, self.title_id, language)] = source
        job = self.editor_executor.submit(self.cache.import_srt, source, self.media_id, self.title_id, language)
        self.jobs.append(("subtitles", self.generation, job))
        self.subtitle_status.setText("テキスト字幕を読み込み中…")

    def _reload_srt(self):
        language = self.active_language
        source = self.srt_sources.get((self.media_id, self.title_id, language))
        if source and Path(source).is_file():
            self._queue_srt(Path(source), language)
        else:
            self._import_subtitles()

    def _open_editor(self):
        language = self.active_language
        index = self.indexes[language]
        if not index.cues:
            self.subtitle_status.setText("先に編集・OCRする字幕トラックを選択してください。")
            return
        if not self.editor_path or not self.editor_path.is_file():
            filename, _ = QFileDialog.getOpenFileName(self, "Subtitle Editの実行ファイルを選択", "",
                                                    "Subtitle Edit (SubtitleEdit.exe);;実行ファイル (*.exe)")
            if not filename:
                return
            self.editor_path = Path(filename)
        parent = self.cache.title_dir(self.media_id, self.title_id) / "ocr"
        executable = self.editor_path
        prefix = f"title-{self.title_id + 1:02d}.{language}-"
        job = self.editor_executor.submit(lambda: (export_for_editor(index, language, parent, prefix),
                                                  executable, language))
        self.jobs.append(("editor", self.generation, job))
        self.subtitle_status.setText("Subtitle Edit用の字幕を書き出しています…")

    def _auto_ocr(self):
        language = self.active_language
        index = self.indexes[language]
        if not index.cues:
            self.subtitle_status.setText("OCRの対象となる字幕がありません。")
            return
        if not self.editor_path or not self.editor_path.is_file():
            filename, _ = QFileDialog.getOpenFileName(self, "Subtitle Editの実行ファイルを選択", "",
                                                    "Subtitle Edit (SubtitleEdit.exe);;実行ファイル (*.exe)")
            if not filename:
                return
            self.editor_path = Path(filename)
        parent = self.cache.title_dir(self.media_id, self.title_id) / "ocr"
        executable = self.editor_path
        prefix = f"title-{self.title_id + 1:02d}.{language}-"
        job = self.editor_executor.submit(lambda: (export_for_editor(index, language, parent, prefix),
                                                  executable, language, True))
        self.jobs.append(("editor", self.generation, job))
        self.subtitle_status.setText("Subtitle Editで自動OCRを実行します…")

    def _apply_subtitles(self, result):
        index, language = result
        self._display_track(index, language)

    def _cancel_extraction(self):
        self.extraction_cancel.set()
        self.extracting = False

    def _stop_extraction(self):
        self._cancel_extraction()
        self.generation += 1
        self.subtitle_status.setText("字幕取得を中止しました。取得済みの字幕は引き続き使用できます。")

    def _start_extraction(self):
        if not self.ready or not self.media_id or self.extracting:
            return
        self.extraction_cancel = threading.Event()
        generation = self.generation
        def notify(kind, payload):
            self.extraction_events.put((generation, kind, payload))
        future = self.executor.submit(DvdSubtitleExtractor(self.cache).extract,
                                      self.loaded_drive, self.media_id, self.title_id,
                                      self.extraction_cancel, notify,
                                      self.cache.language_map(self.media_id, self.title_id))
        self.jobs.append(("extract", generation, future))
        self.extracting = True
        self.subtitle_status.setText("DVD字幕を調べています…")

    def _assign_language(self):
        if not self.unknown_tracks:
            return
        self._stop_extraction()
        mapping = self.cache.language_map(self.media_id, self.title_id)
        for stream in self.unknown_tracks:
            name, accepted = QInputDialog.getItem(self, "字幕の言語", f"字幕トラック {stream} の言語",
                                                  ["スキップ", "英語", "日本語"], editable=False)
            if not accepted:
                return
            if name != "スキップ":
                mapping[stream] = "en" if name == "英語" else "ja"
        try:
            self.cache.save_language_map(self.media_id, self.title_id, mapping)
        except OSError:
            self.subtitle_status.setText("言語指定を保存できませんでした。保存先を確認してください。")
            return
        self._start_extraction()

    def _add_cached_track(self, track, select=True):
        tracks = self.tracks[track.language]
        existing = next((i for i, current in enumerate(tracks)
                         if current[0] == track.track_id), -1)
        if existing < 0:
            tracks.append((track.track_id, track.index))
        else:
            tracks[existing] = (track.track_id, track.index)
        self._refresh_track_menu(track.language)
        if select or self.selected_tracks[track.language] == track.track_id:
            self.selected_tracks[track.language] = track.track_id
            self._refresh_track_menu(track.language)
            self._display_track(track.index, track.language)

    def _refresh_track_menu(self, language):
        menu = self.track_menus[language]
        menu.clear()
        for number, (track_id, index) in enumerate(self.tracks[language]):
            kind = "テキスト" if index.cues and all(c.text is not None for c in index.cues) else "画像"
            action = menu.addAction(f"{kind}トラック {number + 1}")
            action.setCheckable(True)
            action.setChecked(self.selected_tracks[language] == track_id)
            action.triggered.connect(
                lambda checked=False, lang=language, i=number: self._select_track(lang, i))

    def _select_track(self, language, number):
        self.active_language = language
        if 0 <= number < len(self.tracks[language]):
            track_id, index = self.tracks[language][number]
            self.selected_tracks[language] = track_id
            self._refresh_track_menu(language)
            self._display_track(index, language)

    def _display_track(self, index, language):
        listing = self.subtitle_list
        scroll = listing.verticalScrollBar().value()
        self.indexes[language] = index
        listing.clear()
        self.image_rows.clear()
        self.highlight_rows = {"en": set(), "ja": set()}
        cues = sorted(
            ((cue.start_ms, language_order, lang, cue_number, cue)
             for language_order, lang in enumerate(("en", "ja"))
             for cue_number, cue in enumerate(self.indexes[lang].cues)),
            key=lambda row: (row[0], row[1], row[3]),
        )
        self.cue_rows = {"en": [-1] * len(self.indexes["en"].cues),
                         "ja": [-1] * len(self.indexes["ja"].cues)}
        for _, _, cue_language, cue_number, cue in cues:
            label = "EN" if cue_language == "en" else "JA"
            text = f"{label}  {timestamp(cue.start_ms)}"
            if cue.text is not None:
                text += "\n" + cue.text
            item = QListWidgetItem(text)
            if cue.text is not None:
                font = QFont(listing.font())
                font.setPointSizeF(max(20, font.pointSizeF()))
                item.setFont(font)
            item.setSizeHint(QSize(300, 72 if cue.image is not None else 64))
            item.setData(Qt.ItemDataRole.UserRole, (cue_language, cue_number))
            item.setData(Qt.ItemDataRole.UserRole + 1, False)
            item.setData(Qt.ItemDataRole.UserRole + 2, cue.text)
            self.cue_rows[cue_language][cue_number] = listing.count()
            listing.addItem(item)
        self.subtitle_status.setText("この字幕トラックには字幕がありません。" if index.complete and not index.cues
                                     else "テキスト字幕を読み込みました。" if index.cues and index.cues[0].text is not None
                                     else "画像字幕を読み込みました。")
        self.active_rows = {"en": None, "ja": None}
        if not self.follow:
            listing.verticalScrollBar().setValue(scroll)

    def _load_visible_images(self, listing):
        # Load only visible rows; pixmaps outside the viewport are released.
        viewport = listing.viewport().rect()
        display_size = QSize(max(100, min(600, viewport.width() - 70)), 64)
        listing.setIconSize(display_size)
        from PySide6.QtCore import QPoint
        first = listing.indexAt(QPoint(1, 1)).row()
        first = max(0, first)
        visible_rows = set()
        for i in range(first, min(listing.count(), first + 30)):
            if listing.visualItemRect(listing.item(i)).intersects(viewport):
                visible_rows.add(i)
        for i in visible_rows | self.image_rows:
            item = listing.item(i)
            visible = i in visible_rows
            cue_language, cue_number = item.data(Qt.ItemDataRole.UserRole)
            cue = self.indexes[cue_language].cues[cue_number]
            if cue.text is not None:
                continue
            if visible and not item.data(Qt.ItemDataRole.UserRole + 1):
                reader = QImageReader(str(cue.image))
                size = reader.size()
                if not size.isValid() or max(size.width(), size.height()) > 4096:
                    item.setText(f"{'EN' if cue_language == 'en' else 'JA'}  "
                                 f"{timestamp(cue.start_ms)}　画像を読み込めません")
                else:
                    reader.setScaledSize(size.scaled(display_size, Qt.AspectRatioMode.KeepAspectRatio))
                    image = reader.read()
                    if not image.isNull():
                        item.setIcon(QIcon(QPixmap.fromImage(image)))
                    else:
                        item.setText(f"{'EN' if cue_language == 'en' else 'JA'}  "
                                     f"{timestamp(cue.start_ms)}　画像を読み込めません")
                item.setData(Qt.ItemDataRole.UserRole + 1, True)
            elif not visible and item.data(Qt.ItemDataRole.UserRole + 1):
                item.setIcon(QIcon())
                item.setData(Qt.ItemDataRole.UserRole + 1, False)
        self.image_rows = visible_rows

    def _sync(self, ms):
        active_rows = {"en": set(), "ja": set()}
        for language in ("en", "ja"):
            index = self.indexes[language]
            covered = ms >= 0 and index.covers(ms)
            active = index.active(ms) if covered else []
            self.active_rows[language] = tuple(active)
            active_rows[language] = {self.cue_rows[language][i] for i in active}
        highlighted = active_rows["en"] | active_rows["ja"]
        rows_to_update = self.highlight_rows["en"] | self.highlight_rows["ja"] | highlighted
        for row in rows_to_update:
            item = self.subtitle_list.item(row)
            is_active = row in highlighted
            item.setBackground(QColor("#204c53") if is_active else QColor("transparent"))
            item.setForeground(QColor("white") if is_active else QColor("#c8d6e8"))
        self.highlight_rows = active_rows
        self.follow_button.setChecked(self.follow)
        if self.follow and highlighted:
            self.subtitle_list.scrollToItem(self.subtitle_list.item(min(highlighted)),
                                           QListWidget.ScrollHint.PositionAtCenter)
        self._load_visible_images(self.subtitle_list)
        selected = self.active_language
        selected_index = self.indexes[selected]
        self.coverage_status.setText(
            "この位置の字幕は未取得です。"
            if ms >= 0 and not selected_index.covers(ms) else "")

    def _tick(self):
        # Even VLC getters can wait on its input lock. Do not poll the player
        # or process media replacement jobs until navigation has returned.
        if self.navigation_job is not None:
            if not self.navigation_job.done():
                if not self.navigation_reported and time.monotonic() - self.navigation_started > 10:
                    from dvd_player.diagnostics import dump_threads
                    self.navigation_reported = True
                    self.logger.error("NAVIGATION_STALLED kind=%s title=%s", self.navigation_kind, self.title_id)
                    dump_threads(app_data_dir())
                    self.statusBar().showMessage("DVDの応答を待っています。診断ログを保存しました。")
                return
            job, kind = self.navigation_job, self.navigation_kind
            self.navigation_job = self.navigation_kind = None
            try:
                result = job.result()
                self.logger.info("NAVIGATION_DONE kind=%s title=%s", kind, self.title_id)
                if kind == "chapter":
                    self.ready = True
                    self.active_rows = {"en": None, "ja": None}
                    self.statusBar().showMessage("チャプターを移動しました。", 3000)
                elif kind == "prepare":
                    self._complete_preparing(result)
            except Exception:
                self.logger.exception("NAVIGATION_FAILED kind=%s", kind)
                if kind == "chapter":
                    self.ready = True
                    self.statusBar().showMessage("チャプターを移動できませんでした。", 6000)
                else:
                    self.preparing = False
                    self.statusBar().showMessage("DVDの読み込みに失敗しました。開き直してください。", 6000)
        if (self.ready and time.monotonic() - self.last_media_check > 3
                and not any(kind == "presence" for kind, _, _ in self.jobs)):
            self.last_media_check = time.monotonic()
            self.jobs.append(("presence", self.generation,
                              self.media_executor.submit(probe_media, self.loaded_drive, self.media_cancel)))
        while not self.extraction_events.empty():
            generation, kind, payload = self.extraction_events.get()
            if generation != self.generation:
                continue
            if kind == "track":
                self._add_cached_track(payload, select=not self.tracks[payload.language])
            elif kind == "unknown":
                self.unknown_tracks = payload
            else:
                self.subtitle_status.setText(payload)
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
                    self.cache.set_media_name(self.media_id, self.media_name)
                    self._start_title()
                elif kind == "presence":
                    if not result:
                        self._media_removed()
                elif kind == "cache":
                    for track in result:
                        self._add_cached_track(track, select=not self.tracks[track.language])
                    if result:
                        self.subtitle_status.setText("保存済み字幕を自動で読み込みました。")
                    if ({track.language for track in result if track.index.complete} != {"en", "ja"}
                            or any(not track.index.complete for track in result)):
                        self._start_extraction()
                elif kind == "extract":
                    self.extracting = False
                    tracks, unknown = result
                    for track in tracks:
                        self._add_cached_track(track, select=not self.tracks[track.language])
                    self.subtitle_status.setText(f"字幕取得完了：{len(tracks)}トラック。" +
                                                 (f"言語不明の{len(unknown)}トラックは未取得です。" if unknown else ""))
                elif kind == "subtitles":
                    track, warning = result
                    self._add_cached_track(track)
                    if warning:
                        self.subtitle_status.setText("字幕を読み込みました。保存できないため、次回は再読込が必要です。")
                elif kind == "editor":
                    if len(result) == 4:
                        path, executable, language, auto_ocr = result
                        launch_editor(executable, path)
                        srt_path = path.with_suffix(".srt")
                        if srt_path.exists():
                            self.srt_sources[(self.media_id, self.title_id, language)] = srt_path
                            self._queue_srt(srt_path, language)
                        self.subtitle_status.setText("Subtitle Editで自動OCRを起動しました。SRT保存後は自動でテキスト字幕として読み込みます。")
                    else:
                        path, executable, language = result
                        launch_editor(executable, path)
                        self.srt_sources[(self.media_id, self.title_id, language)] = path.with_suffix(".srt")
                        self.subtitle_status.setText("Subtitle EditでOCR／編集し、SRT保存後に「字幕を読み込む」または字幕メニューから再読み込みしてください。")
                else:
                    self._apply_subtitles(result)
            except Exception as error:
                if isinstance(error, ExtractionCancelled):
                    continue
                if kind == "presence":
                    self._media_removed()
                    continue
                if kind == "extract":
                    self.extracting = False
                    if isinstance(error, ExtractionCancelled):
                        continue
                self.logger.warning("LOAD_FAILED operation=%s title=%s", kind, self.title_id)
                if kind == "identity":
                    self.preparing = False
                    self._error("DVDを読み込めません。媒体とドライブを確認してください。")
                else:
                    self.subtitle_status.setText(str(error) if isinstance(error, ValueError) else "字幕を読み込めません。形式と画像を確認してください。")
        if not self.engine or self.navigation_job is not None:
            return
        if not (self.preparing or self.ready):
            self._set_controls(False)
            return
        try:
            p = self.engine.player
            state = p.get_state()
            if self.preparing:
                if state == self.engine.vlc.State.Error or time.monotonic() - self.prepared_at > 20:
                    self._playback_failed()
                elif (state in (self.engine.vlc.State.Playing, self.engine.vlc.State.Paused)
                      and p.get_title() == self.title_id + 1 and p.get_length() > 0):
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
                # DVD navigation needs the input/decoder to advance. Seeking
                # while paused can leave VLC waiting for a position update.
                if not p.is_playing():
                    self.engine.play()
                self.engine.seek(command)
            elif pending and self.seek.target is None:
                self.engine.play() if self.seek.resume else self.engine.pause()
        except (TimeoutError, RuntimeError) as error:
            resume = self.seek.resume
            self.seek.clear()
            self.engine.play() if resume else self.engine.pause()
            self.statusBar().showMessage(str(error), 6000)
        self.time_label.setText(f"{timestamp(actual)} / {timestamp(duration)}")
        if duration > 0 and actual >= 0 and not self.slider.isSliderDown():
            self.slider.setValue(min(10000, actual * 10000 // duration))
        text = "一時停止" if p.is_playing() else "再生"
        if self.play_button.text() != text:
            self.play_button.setText(text)
            self.play_button.setIcon(tint_icon(self.style().standardIcon(
                QStyle.StandardPixmap.SP_MediaPause if p.is_playing() else QStyle.StandardPixmap.SP_MediaPlay), "#10252a"))
        self._sync(actual)

    def _error(self, message):
        self.statusBar().showMessage(message)

    def _media_removed(self):
        self._cancel_extraction()
        self.media_cancel.set()
        self.generation += 1
        self.ready = self.loaded = self.preparing = False
        self.media_id = ""
        self.seek.clear()
        self._reset_subtitles()
        self.titles.clear()
        self._begin_navigation("stop", self.engine.player.stop)
        self.time_label.setText("--:-- / --:--")
        self.slider.setValue(0)
        self.subtitle_status.setText("DVDが取り出されたか、読み取れなくなりました。")
        self._error("DVDを挿入して、もう一度読み込んでください。")
        self.logger.warning("MEDIA_REMOVED")
        self._set_controls(False)

    def _playback_failed(self):
        self._cancel_extraction()
        self.logger.warning("PLAYBACK_FAILED title=%s", self.title_id)
        self.generation += 1
        self.ready = self.loaded = self.preparing = False
        self.seek.clear()
        self._reset_subtitles()
        if self.engine and self.navigation_job is None:
            self._begin_navigation("stop", self.engine.player.stop)
        self._set_controls(False)
        self._error("DVD再生に失敗しました。媒体・リージョン・VLCを確認して再度読み込んでください。")

    def closeEvent(self, event):
        if self.navigation_job is not None and not self.navigation_job.done():
            self.statusBar().showMessage("DVD操作の完了後に閉じてください。")
            event.ignore()
            return
        self._cancel_extraction()
        self.media_cancel.set()
        self.generation += 1
        self.timer.stop()
        for _, _, job in self.jobs:
            job.cancel()
        self.executor.shutdown(wait=False, cancel_futures=True)
        self.editor_executor.shutdown(wait=False, cancel_futures=True)
        self.media_executor.shutdown(wait=False, cancel_futures=True)
        self.navigation_executor.shutdown(wait=False, cancel_futures=True)
        if self.engine:
            self.engine.close()
        event.accept()
