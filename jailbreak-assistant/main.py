from __future__ import annotations

import html
import sys
import traceback
import webbrowser
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QThread, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QFont
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSplitter,
    QTextBrowser,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

import core


class Task(QThread):
    succeeded = Signal(object)
    failed = Signal(str)
    note = Signal(str)

    def __init__(self, function: Callable[[Callable[[str], None]], Any]):
        super().__init__()
        self.function = function

    def run(self) -> None:
        try:
            self.succeeded.emit(self.function(self.note.emit))
        except Exception as exc:
            traceback.print_exc()
            self.failed.emit(str(exc))


class Card(QFrame):
    def __init__(self, title: str, eyebrow: str = ""):
        super().__init__()
        self.setObjectName("card")
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(22, 20, 22, 22)
        self.layout.setSpacing(13)
        if eyebrow:
            kicker = QLabel(eyebrow.upper())
            kicker.setObjectName("eyebrow")
            self.layout.addWidget(kicker)
        heading = QLabel(title)
        heading.setObjectName("cardTitle")
        self.layout.addWidget(heading)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.catalog = core.load_catalog(False)
        self.models, _ = core.load_models(self.catalog, False)
        self.devices: list[core.KindleDevice] = []
        self.results: list[dict[str, Any]] = []
        self.current_result: dict[str, Any] | None = None
        self.tasks: set[Task] = set()
        self.setWindowTitle(f"LazyingArt - {core.APP_NAME}")
        self.resize(1220, 830)
        self.setMinimumSize(900, 650)
        self._build()
        self._style()
        self._populate_models()
        self._set_idle("Ready to identify a Kindle")
        self._refresh_online()
        self.scan_devices()

    def _build(self) -> None:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        root = QWidget()
        scroll.setWidget(root)
        self.setCentralWidget(scroll)
        page = QVBoxLayout(root)
        page.setContentsMargins(34, 28, 34, 38)
        page.setSpacing(20)

        header = QHBoxLayout()
        brand = QVBoxLayout()
        kicker = QLabel("LAZYINGART / OPEN READING")
        kicker.setObjectName("brandKicker")
        title = QLabel("Kindle Jailbreak Assistant")
        title.setObjectName("pageTitle")
        subtitle = QLabel("Detect the device. Match the firmware. Automate only the safe host-side work.")
        subtitle.setObjectName("subtitle")
        brand.addWidget(kicker)
        brand.addWidget(title)
        brand.addWidget(subtitle)
        header.addLayout(brand, 1)
        self.catalog_badge = QLabel(f"Catalog {self.catalog['catalog_version']}")
        self.catalog_badge.setObjectName("badge")
        header.addWidget(self.catalog_badge, 0, Qt.AlignTop)
        page.addLayout(header)

        top = QGridLayout()
        top.setHorizontalSpacing(20)
        top.setVerticalSpacing(20)
        top.setColumnStretch(0, 1)
        top.setColumnStretch(1, 1)

        device_card = Card("Connect your Kindle", "01 / USB")
        self.device_combo = QComboBox()
        self.device_combo.currentIndexChanged.connect(self._device_changed)
        device_card.layout.addWidget(self.device_combo)
        device_buttons = QHBoxLayout()
        self.scan_button = QPushButton("Scan USB")
        self.scan_button.clicked.connect(self.scan_devices)
        browse_button = QPushButton("Choose folder")
        browse_button.setProperty("secondary", True)
        browse_button.clicked.connect(self.choose_device)
        open_button = QPushButton("Open Kindle")
        open_button.setProperty("secondary", True)
        open_button.clicked.connect(self.open_device)
        device_buttons.addWidget(self.scan_button)
        device_buttons.addWidget(browse_button)
        device_buttons.addWidget(open_button)
        device_card.layout.addLayout(device_buttons)
        self.device_info = QLabel("Connect by a data-capable USB cable. MTP-only devices may require a manual mount.")
        self.device_info.setWordWrap(True)
        self.device_info.setObjectName("muted")
        device_card.layout.addWidget(self.device_info)
        top.addWidget(device_card, 0, 0)

        identity_card = Card("Identify model and firmware", "02 / MATCH")
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignRight)
        serial_row = QHBoxLayout()
        self.serial_edit = QLineEdit()
        self.serial_edit.setPlaceholderText("Serial prefix or first 8 characters")
        identify_button = QPushButton("Find")
        identify_button.setProperty("secondary", True)
        identify_button.clicked.connect(self.identify_serial)
        serial_row.addWidget(self.serial_edit, 1)
        serial_row.addWidget(identify_button)
        form.addRow("Serial", serial_row)
        self.model_combo = QComboBox()
        self.model_combo.setMaxVisibleItems(18)
        form.addRow("Model", self.model_combo)
        self.firmware_edit = QLineEdit()
        self.firmware_edit.setPlaceholderText("Example: 5.18.1.1.1")
        form.addRow("Firmware", self.firmware_edit)
        identity_card.layout.addLayout(form)
        top.addWidget(identity_card, 0, 1)

        prerequisites = Card("Confirm current state", "03 / PREREQUISITES")
        state_grid = QGridLayout()
        self.registered_combo = self._state_combo([("Unknown", "unknown"), ("Registered", "yes"), ("Not registered", "no")])
        self.ads_combo = self._state_combo([("Unknown", "unknown"), ("Ads visible", "yes"), ("No ads", "no")])
        self.blacklisted_combo = self._state_combo([("Unknown", "unknown"), ("Blacklisted", "yes"), ("Not blacklisted", "no")])
        self.browser_combo = self._state_combo([("Unknown", "unknown"), ("Chromium browser", "chromium"), ("Legacy/other browser", "other")])
        state_grid.addWidget(QLabel("Account"), 0, 0)
        state_grid.addWidget(self.registered_combo, 0, 1)
        state_grid.addWidget(QLabel("Special Offers"), 0, 2)
        state_grid.addWidget(self.ads_combo, 0, 3)
        state_grid.addWidget(QLabel("Device status"), 1, 0)
        state_grid.addWidget(self.blacklisted_combo, 1, 1)
        state_grid.addWidget(QLabel("Browser"), 1, 2)
        state_grid.addWidget(self.browser_combo, 1, 3)
        prerequisites.layout.addLayout(state_grid)
        analyze_button = QPushButton("Find the safest documented route")
        analyze_button.clicked.connect(self.analyze)
        prerequisites.layout.addWidget(analyze_button)
        top.addWidget(prerequisites, 1, 0, 1, 2)
        page.addLayout(top)

        route_card = Card("Recommended routes", "04 / PLAN")
        splitter = QSplitter(Qt.Horizontal)
        self.route_list = QListWidget()
        self.route_list.setMinimumWidth(300)
        self.route_list.currentItemChanged.connect(self._route_changed)
        self.route_detail = QTextBrowser()
        self.route_detail.setOpenExternalLinks(True)
        splitter.addWidget(self.route_list)
        splitter.addWidget(self.route_detail)
        splitter.setSizes([350, 710])
        route_card.layout.addWidget(splitter)
        route_actions = QHBoxLayout()
        self.guide_button = QPushButton("Official guide")
        self.guide_button.setProperty("secondary", True)
        self.guide_button.clicked.connect(self.open_guide)
        self.download_button = QPushButton("Download + verify")
        self.download_button.setProperty("secondary", True)
        self.download_button.clicked.connect(self.download_selected)
        library_button = QPushButton("All documented methods")
        library_button.setProperty("secondary", True)
        library_button.clicked.connect(lambda: self._open_url(self.catalog["sources"]["all_methods"]))
        route_actions.addWidget(self.guide_button)
        route_actions.addWidget(self.download_button)
        route_actions.addWidget(library_button)
        route_actions.addStretch(1)
        route_card.layout.addLayout(route_actions)
        page.addWidget(route_card)

        action_card = Card("Prepare without hiding the risk", "05 / ACT")
        checks = QGridLayout()
        self.owner_check = QCheckBox("I own or am authorized to modify this Kindle.")
        self.risk_check = QCheckBox("I understand that a wrong firmware or interrupted operation can brick it.")
        self.guide_check = QCheckBox("I opened the official guide and will follow its on-device timing.")
        checks.addWidget(self.owner_check, 0, 0)
        checks.addWidget(self.risk_check, 0, 1)
        checks.addWidget(self.guide_check, 1, 0, 1, 2)
        action_card.layout.addLayout(checks)
        action_buttons = QHBoxLayout()
        self.snapshot_button = QPushButton("Safety snapshot")
        self.snapshot_button.setProperty("secondary", True)
        self.snapshot_button.clicked.connect(self.snapshot)
        self.guard_button = QPushButton("Create 80 MB OTA guard")
        self.guard_button.setProperty("secondary", True)
        self.guard_button.clicked.connect(self.create_guard)
        self.remove_guard_button = QPushButton("Remove OTA guard")
        self.remove_guard_button.setProperty("secondary", True)
        self.remove_guard_button.clicked.connect(self.remove_guard)
        self.prepare_button = QPushButton("Prepare Kindle")
        self.prepare_button.clicked.connect(self.prepare_selected)
        action_buttons.addWidget(self.snapshot_button)
        action_buttons.addWidget(self.guard_button)
        action_buttons.addWidget(self.remove_guard_button)
        action_buttons.addStretch(1)
        action_buttons.addWidget(self.prepare_button)
        action_card.layout.addLayout(action_buttons)
        page.addWidget(action_card)

        finish_card = Card("Finish and make it useful", "06 / POST-JAILBREAK")
        finish_text = QLabel(
            "SpringBreak and Sanctuary include KPM and the hotfix. For older routes, stage the universal hotfix first. "
            "Then install KOReader using the method documented for your jailbreak stack."
        )
        finish_text.setWordWrap(True)
        finish_text.setObjectName("muted")
        finish_card.layout.addWidget(finish_text)
        finish_actions = QHBoxLayout()
        hotfix_button = QPushButton("Stage universal hotfix")
        hotfix_button.setProperty("secondary", True)
        hotfix_button.clicked.connect(self.stage_hotfix)
        koreader_button = QPushButton("KOReader instructions")
        koreader_button.setProperty("secondary", True)
        koreader_button.clicked.connect(self.koreader_help)
        ota_button = QPushButton("Permanent OTA guidance")
        ota_button.setProperty("secondary", True)
        ota_button.clicked.connect(lambda: self._open_url(self.catalog["sources"]["ota"]))
        finish_actions.addWidget(hotfix_button)
        finish_actions.addWidget(koreader_button)
        finish_actions.addWidget(ota_button)
        finish_actions.addStretch(1)
        finish_card.layout.addLayout(finish_actions)
        page.addWidget(finish_card)

        status_card = QFrame()
        status_card.setObjectName("statusCard")
        status_layout = QVBoxLayout(status_card)
        status_top = QHBoxLayout()
        self.status_label = QLabel()
        self.status_label.setObjectName("statusTitle")
        self.progress = QProgressBar()
        self.progress.setMaximumWidth(230)
        self.progress.setTextVisible(False)
        self.progress.hide()
        status_top.addWidget(self.status_label, 1)
        status_top.addWidget(self.progress)
        status_layout.addLayout(status_top)
        self.log = QTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(120)
        status_layout.addWidget(self.log)
        page.addWidget(status_card)

        footer = QLabel("LazyingArt LLC  /  lazying.art/eink  /  Compatibility data: KindleModding.org")
        footer.setObjectName("footer")
        footer.setAlignment(Qt.AlignCenter)
        page.addWidget(footer)

    def _style(self) -> None:
        self.setStyleSheet(
            """
            QMainWindow, QScrollArea, QScrollArea > QWidget > QWidget { background: #f1eee6; }
            QWidget { color: #20231f; font-family: "Segoe UI", "Aptos", sans-serif; font-size: 14px; }
            #brandKicker, #eyebrow { color: #17654a; font-weight: 800; letter-spacing: 2px; font-size: 11px; }
            #pageTitle { font-family: Georgia, serif; font-size: 36px; font-weight: 700; color: #172019; }
            #subtitle, #muted { color: #666b64; }
            #badge { background: #dce8d8; color: #24573f; border: 1px solid #bfd0b9; border-radius: 15px; padding: 8px 13px; font-weight: 700; }
            #card { background: #fbfaf6; border: 1px solid #d8d3c7; border-radius: 16px; }
            #cardTitle { font-family: Georgia, serif; font-size: 22px; font-weight: 700; }
            #statusCard { background: #172019; border-radius: 14px; padding: 10px; }
            #statusTitle { color: #f5f1e8; font-size: 15px; font-weight: 700; }
            #footer { color: #7b7c74; padding: 8px; }
            QLineEdit, QComboBox, QListWidget, QTextBrowser, QTextEdit { background: #ffffff; border: 1px solid #cbc6ba; border-radius: 9px; padding: 8px; selection-background-color: #17654a; }
            QComboBox { min-height: 22px; }
            QListWidget { padding: 6px; }
            QListWidget::item { border-radius: 8px; padding: 12px; margin: 2px; }
            QListWidget::item:selected { background: #dce8d8; color: #163d2c; }
            QTextBrowser { min-height: 250px; line-height: 1.35; }
            QTextEdit { background: #202b22; color: #cfe5d5; border-color: #334437; font-family: Consolas, monospace; }
            QPushButton { background: #17654a; color: white; border: none; border-radius: 9px; padding: 10px 16px; font-weight: 700; }
            QPushButton:hover { background: #0f513a; }
            QPushButton:disabled { background: #b9bbb4; color: #ecece8; }
            QPushButton[secondary="true"] { background: #e8e3d7; color: #30362f; border: 1px solid #d0c9ba; }
            QPushButton[secondary="true"]:hover { background: #ddd6c6; }
            QCheckBox { spacing: 8px; }
            QProgressBar { border: 1px solid #4e6253; border-radius: 6px; background: #243128; height: 10px; }
            QProgressBar::chunk { background: #d48d3a; border-radius: 5px; }
            QSplitter::handle { background: transparent; width: 10px; }
            """
        )

    @staticmethod
    def _state_combo(items: list[tuple[str, str]]) -> QComboBox:
        combo = QComboBox()
        for label, value in items:
            combo.addItem(label, value)
        return combo

    def _populate_models(self, preserve: str = "") -> None:
        if not preserve and self.model_combo.currentData():
            preserve = ",".join(self.model_combo.currentData().get("nicknames", []))
        self.model_combo.blockSignals(True)
        self.model_combo.clear()
        self.model_combo.addItem("Select model...", None)
        selected = 0
        for index, model in enumerate(self.models, start=1):
            aliases = ", ".join(model.get("nicknames", []))
            self.model_combo.addItem(f"{model['amazon_name']}  [{aliases}]", model)
            if preserve and preserve == ",".join(model.get("nicknames", [])):
                selected = index
        self.model_combo.setCurrentIndex(selected)
        self.model_combo.blockSignals(False)

    def _refresh_online(self) -> None:
        def work(note: Callable[[str], None]) -> tuple[dict[str, Any], list[dict[str, Any]], bool]:
            note("Refreshing official compatibility data...")
            catalog = core.load_catalog(True)
            models, online = core.load_models(catalog, True)
            return catalog, models, online

        def done(result: tuple[dict[str, Any], list[dict[str, Any]], bool]) -> None:
            preserve = ",".join((self.model_combo.currentData() or {}).get("nicknames", []))
            self.catalog, self.models, online = result
            self._populate_models(preserve)
            source = "live official matrix" if online else "offline fallback"
            self.catalog_badge.setText(f"Catalog {self.catalog['catalog_version']} / {source}")
            self._set_idle("Compatibility catalog ready")

        self._run_task(work, done, quiet=True)

    def _run_task(
        self,
        function: Callable[[Callable[[str], None]], Any],
        done: Callable[[Any], None] | None = None,
        quiet: bool = False,
    ) -> None:
        task = Task(function)
        self.tasks.add(task)
        if not quiet:
            self.progress.setRange(0, 0)
            self.progress.show()
        task.note.connect(self._log)

        def success(value: Any) -> None:
            self.tasks.discard(task)
            if not self.tasks:
                self.progress.hide()
            if done:
                done(value)

        def failure(message: str) -> None:
            self.tasks.discard(task)
            if not self.tasks:
                self.progress.hide()
            self._set_idle("Action stopped safely")
            self._log(f"ERROR: {message}")
            QMessageBox.critical(self, core.APP_NAME, message)

        task.succeeded.connect(success)
        task.failed.connect(failure)
        task.finished.connect(task.deleteLater)
        task.start()

    def _set_idle(self, text: str) -> None:
        self.status_label.setText(text)

    def _log(self, text: str) -> None:
        self.status_label.setText(text)
        self.log.append(text)

    def scan_devices(self) -> None:
        self.scan_button.setEnabled(False)

        def done(devices: list[core.KindleDevice]) -> None:
            self.scan_button.setEnabled(True)
            self.devices = devices
            self.device_combo.clear()
            if not devices:
                self.device_combo.addItem("No mounted Kindle found", None)
                self.device_info.setText("No USB filesystem matched Kindle markers. Try another cable, unlock/mount the device, or choose its folder.")
                self._set_idle("No mounted Kindle detected")
                return
            for device in devices:
                self.device_combo.addItem(device.display, device)
            self._set_idle(f"Detected {len(devices)} Kindle filesystem(s)")

        self._run_task(lambda note: core.discover_kindles(), done)

    def choose_device(self) -> None:
        selected = QFileDialog.getExistingDirectory(self, "Choose the mounted Kindle root")
        if not selected:
            return
        try:
            device = core.inspect_device(Path(selected))
        except Exception as exc:
            QMessageBox.critical(self, core.APP_NAME, str(exc))
            return
        self.device_combo.addItem(device.display, device)
        self.device_combo.setCurrentIndex(self.device_combo.count() - 1)

    def _device_changed(self) -> None:
        device = self.current_device()
        if not device:
            return
        self.device_info.setText(
            f"{device.root}  /  {device.free / (1024 ** 3):.2f} GiB free of {device.total / (1024 ** 3):.2f} GiB"
        )
        if device.firmware and not self.firmware_edit.text().strip():
            self.firmware_edit.setText(device.firmware)
        if device.serial and not self.serial_edit.text().strip():
            self.serial_edit.setText(device.serial)

    def current_device(self) -> core.KindleDevice | None:
        value = self.device_combo.currentData()
        return value if isinstance(value, core.KindleDevice) else None

    def identify_serial(self) -> None:
        serial = self.serial_edit.text().strip()
        model = core.identify_model(serial, self.models)
        if model is None:
            QMessageBox.information(
                self,
                core.APP_NAME,
                "That serial prefix is not in the current official matrix. Select the model manually and do not paste a full serial into support posts.",
            )
            return
        for index in range(self.model_combo.count()):
            candidate = self.model_combo.itemData(index)
            if candidate and candidate.get("amazon_name") == model.get("amazon_name"):
                self.model_combo.setCurrentIndex(index)
                break
        self._log(f"Matched serial prefix to {model['amazon_name']}")

    def analyze(self) -> None:
        model = self.model_combo.currentData()
        if model is None:
            QMessageBox.information(self, core.APP_NAME, "Select the Kindle model first.")
            return
        state = {
            "registered": self.registered_combo.currentData(),
            "ads": self.ads_combo.currentData(),
            "blacklisted": self.blacklisted_combo.currentData(),
            "browser": self.browser_combo.currentData(),
        }
        self.results = core.analyze(self.catalog, model, self.firmware_edit.text().strip(), state)
        self.route_list.clear()
        if not self.results:
            self.current_result = None
            self.route_detail.setHtml(
                "<h2>No safe public route matched</h2><p>Do not downgrade or copy a payload from another model. "
                "Check the live official model finder and wait for a documented method.</p>"
            )
            self._update_actions()
            self._set_idle("No documented compatible route found")
            return
        for result in self.results:
            status = {"compatible": "READY", "conditional": "CHECK", "manual": "GUIDE"}[result["status"]]
            item = QListWidgetItem(f"{status}   {result['method']['name']}\n{result['method']['summary']}")
            item.setData(Qt.UserRole, result)
            self.route_list.addItem(item)
        self.route_list.setCurrentRow(0)
        self._set_idle(f"Found {len(self.results)} documented route(s)")

    def _route_changed(self, current: QListWidgetItem | None) -> None:
        self.current_result = current.data(Qt.UserRole) if current else None
        if not self.current_result:
            self.route_detail.clear()
            self._update_actions()
            return
        result = self.current_result
        method = result["method"]
        requirements = result["missing"] + result["unmet"]
        requirement_html = "".join(f"<li>{html.escape(item)}</li>" for item in requirements) or "<li>All entered prerequisites match.</li>"
        steps = "".join(f"<li>{html.escape(step)}</li>" for step in method.get("steps", []))
        platform_note = "" if result["platform_ok"] else "<p><b>This host OS is guide-only for this method.</b></p>"
        post = html.escape(method.get("post_note", "Follow the official post-jailbreak guide."))
        self.route_detail.setHtml(
            f"<h2>{html.escape(method['name'])}</h2>"
            f"<p>{html.escape(method['summary'])}</p>"
            f"<p><b>Match:</b> {html.escape(result['firmware_reason'])}</p>"
            f"{platform_note}<h3>Confirm before continuing</h3><ul>{requirement_html}</ul>"
            f"<h3>Workflow</h3><ol>{steps}</ol>"
            f"<p><b>After success:</b> {post}</p>"
            f"<p><a href=\"{html.escape(method['guide_url'])}\">Read the authoritative guide</a></p>"
        )
        self._update_actions()

    def _update_actions(self) -> None:
        result = self.current_result
        method = result["method"] if result else None
        self.guide_button.setEnabled(bool(method))
        self.download_button.setEnabled(bool(method and method.get("package")))
        kind = method.get("kind") if method else ""
        self.prepare_button.setText("Run official helper" if kind == "runner" else "Prepare Kindle")
        self.prepare_button.setEnabled(bool(method))
        guard_mode = method.get("space_guard", "optional") if method else "optional"
        self.guard_button.setEnabled(guard_mode != "forbidden")
        if guard_mode == "required":
            self.guard_button.setText("Create required 80 MB OTA guard")
        elif guard_mode == "forbidden":
            self.guard_button.setText("OTA guard conflicts with this route")
        else:
            self.guard_button.setText("Create 80 MB OTA guard")

    def _accepted(self) -> bool:
        return self.owner_check.isChecked() and self.risk_check.isChecked() and self.guide_check.isChecked()

    def _require_device(self) -> core.KindleDevice | None:
        device = self.current_device()
        if not device:
            QMessageBox.information(self, core.APP_NAME, "Connect or choose the mounted Kindle first.")
        return device

    def open_device(self) -> None:
        device = self._require_device()
        if device:
            core.open_path(device.root)

    def open_guide(self) -> None:
        if self.current_result:
            self._open_url(self.current_result["method"]["guide_url"])

    @staticmethod
    def _open_url(url: str) -> None:
        QDesktopServices.openUrl(QUrl(url))

    def download_selected(self) -> None:
        if not self.current_result:
            return
        method = self.current_result["method"]

        def done(path: Path) -> None:
            self._log(f"Verified package cached at {path}")
            QMessageBox.information(self, core.APP_NAME, f"Official package downloaded and verified.\n\n{path}")

        self._run_task(lambda note: core.download_package(method, note), done)

    def prepare_selected(self) -> None:
        if not self.current_result:
            return
        if not self._accepted():
            QMessageBox.information(self, core.APP_NAME, "Confirm all three authorization and risk checks first.")
            return
        method = self.current_result["method"]
        if self.current_result["status"] == "conditional":
            answer = QMessageBox.warning(
                self,
                core.APP_NAME,
                "One or more prerequisites are unknown or unmet. The app will not claim compatibility. Open the official guide instead?",
                QMessageBox.Open | QMessageBox.Cancel,
                QMessageBox.Open,
            )
            if answer == QMessageBox.Open:
                self._open_url(method["guide_url"])
            return
        if method["kind"] in {"web", "guide", "hardware"}:
            self._open_url(method["guide_url"])
            return
        device = self.current_device()
        if method["kind"] != "runner" and device is None:
            self._require_device()
            return
        confirmation = QMessageBox.question(
            self,
            core.APP_NAME,
            f"Prepare {method['name']} now?\n\nConflicting files are backed up before replacement. Keep the USB cable connected until completion.",
            QMessageBox.Yes | QMessageBox.Cancel,
            QMessageBox.Cancel,
        )
        if confirmation != QMessageBox.Yes:
            return

        def done(result: dict[str, Any]) -> None:
            if result["kind"] == "runner":
                core.launch_runner(result["runner"])
                self._log("Official helper launched in a terminal. Follow its prompts, then return to the official guide.")
                return
            self._log(f"Staging complete. Backup: {result.get('backup', 'none')}")
            QMessageBox.information(
                self,
                core.APP_NAME,
                f"Host-side preparation completed.\n\nFiles staged: {result.get('copied', 0)}\nBackup: {result.get('backup', 'none')}\n\nEject safely and continue at the official on-device step.",
            )

        root = device.root if device else None
        self._run_task(lambda note: core.prepare_method(method, root, note), done)

    def snapshot(self) -> None:
        device = self._require_device()
        if not device:
            return

        def done(path: Path) -> None:
            self._log(f"Safety snapshot saved to {path}")

        self._run_task(lambda note: core.create_safety_snapshot(device.root), done)

    def create_guard(self) -> None:
        device = self._require_device()
        if not device:
            return
        if self.current_result and self.current_result["method"].get("space_guard") == "forbidden":
            QMessageBox.warning(self, core.APP_NAME, "This route requires free space. Remove old filler files instead.")
            return
        answer = QMessageBox.warning(
            self,
            core.APP_NAME,
            "This writes reversible filler files until about 80 MB remains. It can take several minutes. Do not unplug the Kindle. Continue?",
            QMessageBox.Yes | QMessageBox.Cancel,
            QMessageBox.Cancel,
        )
        if answer != QMessageBox.Yes:
            return

        def done(result: dict[str, Any]) -> None:
            self._log(f"OTA guard created: {result['written'] / (1024 ** 2):.0f} MiB written; {result['free'] / (1024 ** 2):.0f} MiB free")

        self._run_task(lambda note: core.create_space_guard(device.root, 80, note), done)

    def remove_guard(self) -> None:
        device = self._require_device()
        if not device:
            return

        def done(size: int) -> None:
            self._log(f"Removed reversible OTA guard ({size / (1024 ** 2):.0f} MiB)")

        self._run_task(lambda note: core.remove_space_guard(device.root), done)

    def stage_hotfix(self) -> None:
        device = self._require_device()
        if not device:
            return
        answer = QMessageBox.question(
            self,
            core.APP_NAME,
            "Stage the verified universal hotfix at the Kindle root? Do this only after the initial jailbreak succeeds.",
            QMessageBox.Yes | QMessageBox.Cancel,
            QMessageBox.Cancel,
        )
        if answer != QMessageBox.Yes:
            return
        method = core.method_by_id(self.catalog, "post-hotfix")

        def done(result: dict[str, Any]) -> None:
            self._log(f"Universal hotfix staged. Backup: {result.get('backup', 'none')}")
            self._open_url(method["guide_url"])

        self._run_task(lambda note: core.prepare_method(method, device.root, note), done)

    def koreader_help(self) -> None:
        QMessageBox.information(
            self,
            core.APP_NAME,
            "On SpringBreak/Sanctuary stacks, enter these in the Kindle search bar:\n\n;kpm update\n;kpm install koreader\n\nFor older stacks, follow the linked KUAL/MRPI instructions instead.",
        )
        self._open_url(self.catalog["sources"]["koreader"])


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName(core.APP_NAME)
    app.setOrganizationName("LazyingArt LLC")
    app.setOrganizationDomain("lazying.art")
    app.setFont(QFont("Segoe UI", 10))
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

