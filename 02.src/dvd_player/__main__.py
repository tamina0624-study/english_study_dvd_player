import sys
import os
from pathlib import Path


def configure_font(app):
    from PySide6.QtGui import QFont, QFontDatabase
    # Offscreen rendering does not always discover Windows system fonts.
    if os.name == "nt" and not QFontDatabase.families():
        font = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts" / "meiryo.ttc"
        font_id = QFontDatabase.addApplicationFont(str(font))
        families = QFontDatabase.applicationFontFamilies(font_id)
        if families:
            app.setFont(QFont(families[0], 10))


def main():
    from PySide6.QtWidgets import QApplication
    from dvd_player.window import MainWindow
    app = QApplication(sys.argv)
    app.setApplicationName("English DVD Player")
    app.setOrganizationName("dvd_player")
    configure_font(app)
    from dvd_player.diagnostics import install_hang_diagnostics
    from dvd_player.storage import app_data_dir, setup_logging
    logger = setup_logging(app_data_dir())
    logger.info("APPLICATION_STARTED pid=%s source=%s", os.getpid(), Path(__file__).resolve())
    install_hang_diagnostics(app, app_data_dir())
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
