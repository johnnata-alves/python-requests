import os
import sys
from datetime import datetime

os.environ.setdefault("QT_LOGGING_RULES", "qt.qpa.fonts.warning=false")

import jwt
from dotenv import load_dotenv, set_key
from PyQt6.QtCore import QUrl
from PyQt6.QtWebEngineCore import QWebEngineProfile
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget

class BrowserWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.initUI()

    def initUI(self):
        self.setWindowTitle("Embedded Browser")
        self.setGeometry(100, 100, 800, 600)

        central_widget = QWidget()
        self.setCentralWidget(central_widget)

        layout = QVBoxLayout()
        central_widget.setLayout(layout)

        self.browser = QWebEngineView()
        layout.addWidget(self.browser)

        self.browser.setUrl(
            QUrl(os.environ.get("FLOW_LOGIN_URL", "https://flow.ciandt.com/account/sign-in"))
        )

        profile = QWebEngineProfile.defaultProfile()
        self.cookie_store = profile.cookieStore()
        self.cookie_store.cookieAdded.connect(self.cookie_added)

        self.cookie_list = []

    def cookie_added(self, cookie):
        if cookie.name() == b"FlowToken":
            flow_token = str(cookie.value(), "utf-8")
            decoded = jwt.decode(flow_token, options={"verify_signature": False})
            if datetime.fromtimestamp(decoded["exp"]) > datetime.now():
                os.environ["FLOW_TOKEN"] = flow_token
                set_key(".env", "FLOW_TOKEN", flow_token)
                self.cookie_list.append(cookie.name())
        elif cookie.name() == b"FlowTenant":
            flow_tenant = str(cookie.value(), "utf-8")
            set_key(".env", "FLOW_TENANT", flow_tenant)
            self.cookie_list.append(cookie.name())

        if len(self.cookie_list) == 2:
            self.close()

if __name__ == "__main__":
    load_dotenv()

    flow_token = os.environ.get("FLOW_TOKEN")
    if flow_token:
        decoded = jwt.decode(flow_token, options={"verify_signature": False})
        if datetime.fromtimestamp(decoded["exp"]) > datetime.now():
            sys.exit()

    app = QApplication(sys.argv)
    mainWindow = BrowserWindow()
    mainWindow.show()
    sys.exit(app.exec())
