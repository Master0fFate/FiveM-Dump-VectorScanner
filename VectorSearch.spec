# -*- mode: python ; coding: utf-8 -*-
# This Widgets-only application does not import QML, Quick, networking or DBus.
# qwebgl is the optional remote WebGL platform; qxdgdesktopportal is Linux-only;
# qtuiotouchplugin is the optional network TUIO input bridge. None participates
# in native Windows/offscreen Widgets operation. Both platform paths are smoked.
a = Analysis(
    ['VectorSearch.py'],
    pathex=[], binaries=[], datas=[], hiddenimports=[], hookspath=[],
    hooksconfig={}, runtime_hooks=[],
    excludes=['PyQt5.QtQml', 'PyQt5.QtQuick', 'PyQt5.QtNetwork',
              'PyQt5.QtDBus', 'PyQt5.QtWebSockets'],
    noarchive=False,
)
UNUSED_DLLS = {
    'qt5qml.dll', 'qt5qmlmodels.dll', 'qt5quick.dll', 'qt5network.dll',
    'qt5dbus.dll', 'qt5websockets.dll', 'qwebgl.dll',
    'qxdgdesktopportal.dll', 'qtuiotouchplugin.dll',
}

def needed(entry):
    name = entry[0].replace('\\', '/').lower()
    # No QTranslator is installed by this English-language application.
    return name.rsplit('/', 1)[-1] not in UNUSED_DLLS and '/translations/' not in name

a.binaries = [entry for entry in a.binaries if needed(entry)]
a.datas = [entry for entry in a.datas if needed(entry)]
# Retain native/offscreen platform plugins, Windows style, image/icon plugins
# and QtGui graphics fallbacks; do not assume they are safe to strip on all GPUs.
pyz = PYZ(a.pure)
exe = EXE(
    pyz, a.scripts, a.binaries, a.datas, [],
    name='VectorSearch', debug=False, bootloader_ignore_signals=False,
    strip=False, upx=False, console=False,
)
