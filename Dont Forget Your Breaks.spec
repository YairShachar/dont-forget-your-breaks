# -*- mode: python ; coding: utf-8 -*-

with open('VERSION') as _vf:
    APP_VERSION = _vf.read().strip()

a = Analysis(
    ['launch.py'],
    pathex=[],
    binaries=[],
    datas=[('VERSION', '.'), ('assets/icons', 'assets/icons')],
    # pyobjc frameworks are imported lazily inside functions (macOS sensors +
    # window helper), so declare them explicitly to guarantee they're bundled.
    hiddenimports=['Quartz', 'AppKit', 'CoreAudio', 'objc'],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name='Dont Forget Your Breaks',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)
app = BUNDLE(
    exe,
    name='Dont Forget Your Breaks.app',
    icon='assets/AppIcon.icns',
    bundle_identifier='com.yairs.dontforgetyourbreaks',
    info_plist={
        # Dock / ⌘-Tab / Finder show the real name (with apostrophe) + a real icon;
        # version is read from VERSION so it stops reporting 0.0.0.
        'CFBundleName': "Don't Forget Your Breaks",
        'CFBundleDisplayName': "Don't Forget Your Breaks",
        'CFBundleShortVersionString': APP_VERSION,
        'CFBundleVersion': APP_VERSION,
        'NSHighResolutionCapable': True,
    },
)
