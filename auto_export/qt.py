#!/usr/bin/env python
#
# Electrum - Lightweight Bitcoin Client
# Copyright (C) 2015 Thomas Voegtlin
#
# Permission is hereby granted, free of charge, to any person
# obtaining a copy of this software and associated documentation files
# (the "Software"), to deal in the Software without restriction,
# including without limitation the rights to use, copy, modify, merge,
# publish, distribute, sublicense, and/or sell copies of the Software,
# and to permit persons to whom the Software is furnished to do so,
# subject to the following conditions:
#
# The above copyright notice and this permission notice shall be
# included in all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND,
# EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF
# MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND
# NONINFRINGEMENT. IN NO EVENT SHALL THE AUTHORS OR COPYRIGHT HOLDERS
# BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN
# ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN
# CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
# SOFTWARE.

import os
import time
import threading
import csv
from functools import partial
from ftplib import FTP
from io import BytesIO, StringIO

from PyQt5.QtGui import *
from PyQt5.QtWidgets import (QVBoxLayout, QLabel, QGridLayout, QLineEdit, QTabWidget, QWidget, QCheckBox)

from electrum.plugins import BasePlugin, hook
from electrum.i18n import _
from electrum.util import print_msg, print_error, format_satoshis, format_time
from electrum_gui.qt.main_window import StatusBarButton
from electrum_gui.qt.util import EnterButton, Buttons, CloseButton
from electrum_gui.qt.util import OkButton, WindowModalDialog


class Plugin(BasePlugin):

    wallet = None
    timer = None

    def fullname(self):
        return 'AutoExport'

    def description(self):
        return _("Auto Export Plugin")

    def is_available(self):
        return True

    def __init__(self, parent, config, name):
        BasePlugin.__init__(self, parent, config, name)
        self.update_settings(initial=True)

    @staticmethod
    def call_repeatedly(interval, func, *args):
        stopped = threading.Event()
        def loop():
            while not stopped.wait(interval): # the first call is in `interval` secs
                func(*args)
        threading.Thread(target=loop).start()    
        return stopped.set

    def auto_export_enabled(self):
        return self.autoexport_need_export_to_local or self.autoexport_need_export_to_ftp

    def export_csv(self):
        if self.autoexport_need_export_to_local:
            self.export_csv_local()
        if self.autoexport_need_export_to_ftp:
            self.export_csv_ftp()

    def get_exported_data(self):
        history = self.wallet.get_history()
        lines = [["transaction_hash","label", "confirmations", "value", "timestamp"]]
        for item in history:
            tx_hash, height, confirmations, timestamp, value, balance = item
            if height > 0:
                if timestamp is not None:
                    time_string = format_time(timestamp)
                else:
                    time_string = _("unverified")
            else:
                time_string = _("unconfirmed")

            if value is not None:
                value_string = format_satoshis(value, True)
            else:
                value_string = '--'

            if tx_hash:
                label = self.wallet.get_label(tx_hash)
            else:
                label = ""

            lines.append([tx_hash, label, confirmations, value_string, time_string])
        return lines

    def export_csv_local(self):
        try:
            if not self.autoexport_local_path:
                return
            filename = time.strftime("%Y_%m_%d__%H_%M_%S") + '.csv'
            filepath = os.path.join(self.autoexport_local_path, filename)

            lines = self.get_exported_data()

            with open(filepath, "w+") as f:
                transaction = csv.writer(f, lineterminator='\n')
                for line in lines:
                    transaction.writerow(line)
        except Exception as e:
            print_error(str(e))

    @hook
    def create_status_bar(self, sb):
        if self.autoexport_interval_seconds and (self.auto_export_enabled()):
            auto_export = _("AutoExport: {}sec.".format(self.autoexport_interval_seconds))
            self.status_button = StatusBarButton(
                QIcon(":icons/status_connected.png"),
                auto_export,
                lambda: self.settings_dialog(self, self.window)
            )
        else:
            self.status_button = StatusBarButton(
                QIcon(":icons/status_disconnected.png"),
                _("AutoExport"),
                lambda: self.settings_dialog(self, self.window)
            )
        sb.addPermanentWidget(self.status_button)
        return sb

    def export_csv_ftp(self):
        try:
            if not self.autoexport_ftp_host or not self.autoexport_ftp_port:
                return
            if not self.autoexport_ftp_user or not self.autoexport_ftp_password:
                return
            filename = time.strftime("%Y_%m_%d__%H_%M_%S") + '.csv'

            lines = self.get_exported_data()

            ftp = FTP()
            ftp.connect(self.autoexport_ftp_host, int(self.autoexport_ftp_port))
            ftp.login(self.autoexport_ftp_user, self.autoexport_ftp_password)
            if self.autoexport_ftp_dir:
                ftp.cwd(self.autoexport_ftp_dir)

            str_f = StringIO()
            transaction = csv.writer(str_f, lineterminator='\n')
            for line in lines:
                transaction.writerow(line)
            f = BytesIO(str_f.getvalue().encode('utf-8'))
            ftp.storlines("STOR " + filename, f)
            str_f.close()
            f.close()
            
            ftp.close()
        except Exception as e:
            print_error(str(e))

    @hook
    def load_wallet(self, wallet, window):
        self.window = window
        self.wallet = wallet
        if not self.wallet or not self.autoexport_interval_seconds:
            return
        self.timer = self.call_repeatedly(self.autoexport_interval_seconds, self.export_csv)

    @hook
    def close_wallet(self, wallet):
        self.wallet = None
        if self.timer:
            self.timer()

    def requires_settings(self):
        return True

    def settings_widget(self, window):
        return EnterButton(_('Settings'), partial(self.settings_dialog, window))

    def update_settings(self, initial=False):
        self.autoexport_interval_seconds = self.config.get('autoexport_interval_seconds', 0)
        self.autoexport_need_export_to_local = self.config.get('autoexport_need_export_to_local', False)
        self.autoexport_need_export_to_ftp = self.config.get('autoexport_need_export_to_ftp', False)
        self.autoexport_local_path = self.config.get('autoexport_local_path', '')
        self.autoexport_ftp_host = self.config.get('autoexport_ftp_host', '')
        self.autoexport_ftp_port = self.config.get('autoexport_ftp_port', 21)
        self.autoexport_ftp_user = self.config.get('autoexport_ftp_user', '')
        self.autoexport_ftp_password = self.config.get('autoexport_ftp_password', '')
        self.autoexport_ftp_dir = self.config.get('autoexport_ftp_dir', '')
        if self.timer:
            self.timer()
        self.timer = None
        if initial or not self.wallet or not self.autoexport_interval_seconds:
            return
        self.timer = self.call_repeatedly(self.autoexport_interval_seconds, self.export_csv)
        if self.autoexport_interval_seconds and (self.auto_export_enabled()):
            auto_export = _("AutoExport: {}sec.".format(self.autoexport_interval_seconds))
            self.status_button.setToolTip(auto_export)
            self.status_button.setIcon(QIcon(":icons/status_connected.png"))
        else:
            self.status_button.setToolTip(_("AutoExport"))
            self.status_button.setIcon(QIcon(":icons/status_disconnected.png"))

    def settings_dialog(self, window):
        d = WindowModalDialog(window, _("AutoExport settings"))
        d.setMinimumSize(500, 200)
        layout = QVBoxLayout(d)

        # Initialize tab screen
        tabs = QTabWidget()
        tab0 = QWidget()
        tab1 = QWidget()
        tab2 = QWidget()
        tabs.resize(500, 200)

        # Add tabs
        tabs.addTab(tab0, _('Interval'))
        tabs.addTab(tab1, _('Local'))
        tabs.addTab(tab2, _('FTP'))

        # Create Interval tab
        grid = QGridLayout()
        tab0.layout = grid

        grid.addWidget(QLabel('Interval to auto export in seconds'), 0, 0)
        export_interval_seconds = QLineEdit()
        export_interval_seconds.setValidator(QIntValidator())
        try:
            default_value = str(int(self.autoexport_interval_seconds))
        except:
            default_value = '0'
        export_interval_seconds.setText(default_value)
        grid.addWidget(export_interval_seconds, 0, 1)

        tab0.setLayout(tab0.layout)

        # Create LocalExport tab
        grid = QGridLayout()
        tab1.layout = grid

        grid.addWidget(QLabel('Need export to local path'), 0, 0)
        export_need_export_to_local = QCheckBox()
        try:
            default_value = bool(self.autoexport_need_export_to_local)
        except:
            default_value = False
        export_need_export_to_local.setChecked(default_value)
        grid.addWidget(export_need_export_to_local, 0, 1)

        grid.addWidget(QLabel('Local path'), 1, 0)
        export_local_path = QLineEdit()
        try:
            default_value = str(self.autoexport_local_path)
        except:
            default_value = ''
        export_local_path.setText(default_value)
        grid.addWidget(export_local_path, 1, 1)

        tab1.setLayout(tab1.layout)

        # Create FTPExport tab
        grid = QGridLayout()
        tab2.layout = grid

        grid.addWidget(QLabel('Need export to ftp'), 0, 0)
        export_need_export_to_ftp = QCheckBox()
        try:
            default_value = bool(self.autoexport_need_export_to_ftp)
        except:
            default_value = False
        export_need_export_to_ftp.setChecked(default_value)
        grid.addWidget(export_need_export_to_ftp, 0, 1)

        grid.addWidget(QLabel('FTP Host'), 1, 0)
        export_ftp_host = QLineEdit()
        try:
            default_value = str(self.autoexport_ftp_host)
        except:
            default_value = ''
        export_ftp_host.setText(default_value)
        grid.addWidget(export_ftp_host, 1, 1)

        grid.addWidget(QLabel('FTP port'), 1, 2)
        export_ftp_port = QLineEdit()
        export_ftp_port.setValidator(QIntValidator())
        try:
            default_value = str(int(self.autoexport_ftp_port))
        except:
            default_value = '21'
        export_ftp_port.setText(default_value)
        grid.addWidget(export_ftp_port, 1, 3)

        grid.addWidget(QLabel('FTP user'), 2, 0)
        export_ftp_user = QLineEdit()
        try:
            default_value = str(self.autoexport_ftp_user)
        except:
            default_value = ''
        export_ftp_user.setText(default_value)
        grid.addWidget(export_ftp_user, 2, 1)

        grid.addWidget(QLabel('FTP password'), 2, 2)
        export_ftp_password = QLineEdit()
        try:
            default_value = str(self.autoexport_ftp_password)
        except:
            default_value = ''
        export_ftp_password.setEchoMode(QLineEdit.Password)
        export_ftp_password.setText(default_value)
        grid.addWidget(export_ftp_password, 2, 3)

        grid.addWidget(QLabel('FTP path'), 3, 0)
        export_ftp_dir = QLineEdit()
        try:
            default_value = str(self.autoexport_ftp_dir)
        except:
            default_value = ''
        export_ftp_dir.setText(default_value)
        grid.addWidget(export_ftp_dir, 3, 1)

        tab2.setLayout(tab2.layout)

        # Add tabs to widget
        layout.addWidget(tabs)

        layout.addStretch()
        layout.addLayout(Buttons(CloseButton(d), OkButton(d)))

        if not d.exec_():
            return

        try:
            int_export_interval_seconds = int(export_interval_seconds.text())
        except:
            int_export_interval_seconds = 0

        self.config.set_key('autoexport_interval_seconds', int_export_interval_seconds)
        self.config.set_key('autoexport_need_export_to_ftp', export_need_export_to_ftp.isChecked())
        self.config.set_key('autoexport_need_export_to_local', export_need_export_to_local.isChecked())
        self.config.set_key('autoexport_local_path', export_local_path.text())
        self.config.set_key('autoexport_ftp_host', export_ftp_host.text())
        self.config.set_key('autoexport_ftp_port', export_ftp_port.text())
        self.config.set_key('autoexport_ftp_user', export_ftp_user.text())
        self.config.set_key('autoexport_ftp_password', export_ftp_password.text())
        self.config.set_key('autoexport_ftp_dir', export_ftp_dir.text())

        self.update_settings()
