"""Entry point: python3 -m qnotebook"""

import sys

from PyQt6.QtWidgets import QApplication

from qnotebook.window import MainWindow


def main(argv: list[str] | None = None) -> int:
    argv = argv if argv is not None else sys.argv
    app = QApplication(argv)
    app.setApplicationName("qnotebook")
    app.setOrganizationName("qnotebook")
    notebook = argv[1] if len(argv) > 1 else None
    win = MainWindow(notebook_path=notebook)
    win.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
