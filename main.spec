# -*- mode: python ; coding: utf-8 -*-

# PyInstaller spec file for Shadowverse Automation UI
# 特别注意：使用虚拟环境打包，排除配置文件目录

import os
import sys
from PyInstaller.utils.hooks import collect_submodules

# 获取项目根目录
try:
    project_root = os.path.abspath(os.path.dirname(__file__))
except NameError:
    project_root = os.path.abspath(os.getcwd())

# 主脚本文件
main_script = os.path.join(project_root, 'main_ui.py')

# 设置虚拟环境路径（根据实际情况调整）
venv_path = os.path.join(project_root, '.venv')
if os.path.exists(venv_path):
    # 添加虚拟环境的site-packages到路径
    site_packages = os.path.join(venv_path, 'Lib', 'site-packages')
    if os.path.exists(site_packages):
        sys.path.insert(0, site_packages)

# 数据文件 - 只包含必要的运行时资源
# 特别注意：排除quanka、Image、templates、templates_global等配置文件目录
datas = []

# 包含核心资源目录
core_dirs = ['models']
for d in core_dirs:
    src = os.path.join(project_root, d)
    if os.path.exists(src):
        datas.append((src, d))

# 包含uiautomator2的assets资源文件
uiautomator2_assets = os.path.join(venv_path, 'Lib', 'site-packages', 'uiautomator2', 'assets')
if os.path.exists(uiautomator2_assets):
    datas.append((uiautomator2_assets, 'uiautomator2/assets'))

# 包含必要的配置文件
config_files = ['LICENSE', 'README.md', 'PACKAGING.md']
for fname in config_files:
    fpath = os.path.join(project_root, fname)
    if os.path.exists(fpath):
        datas.append((fpath, '.'))

# 排除的目录（这些是用户可自定义的配置文件，不打包进程序）
excluded_dirs = [
    'quanka',
    'Image', 
    'templates',
    'templates_global',
    'shadowverse_cards_cost'
]

# 排除的配置文件（用户可自定义的配置文件，不打包进程序）
excluded_files = [
    'config.json'
]

# 隐藏导入
hiddenimports = collect_submodules('PyQt5') + [
    'numpy', 'pandas', 'cv2', 'PIL', 'torch', 'torchvision',
    'requests', 'scipy', 'sklearn', 'shapely', 'easyocr',
    'adbutils', 'uiautomator2', 'flask', 'colorama', 'click'
]

binaries = []
excludes = []

# 添加PyQt5插件
pyqt5_plugin_dirs = []
try:
    import PyQt5
    pyqt5_path = os.path.dirname(PyQt5.__file__)
    
    # 查找插件目录
    possible_plugin_paths = [
        os.path.join(pyqt5_path, 'Qt', 'plugins'),
        os.path.join(pyqt5_path, 'plugins'),
        os.path.join(sys.prefix, 'Lib', 'site-packages', 'PyQt5', 'Qt', 'plugins'),
        os.path.join(sys.prefix, 'Lib', 'site-packages', 'PyQt5', 'plugins'),
        os.path.join(venv_path, 'Lib', 'site-packages', 'PyQt5', 'Qt', 'plugins'),
        os.path.join(venv_path, 'Lib', 'site-packages', 'PyQt5', 'plugins')
    ]
    
    for plugin_root in possible_plugin_paths:
        if os.path.isdir(plugin_root):
            for name in ('platforms', 'imageformats'):
                src = os.path.join(plugin_root, name)
                if os.path.isdir(src):
                    dest = os.path.join('PyQt5', 'Qt', 'plugins', name)
                    datas.append((src, dest))
                    break
            break

except ImportError:
    print("警告: 无法导入PyQt5，插件可能无法正确包含")

# 分析阶段
a = Analysis(
    [main_script],
    pathex=[project_root, site_packages] if 'site_packages' in locals() else [project_root],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    runtime_hooks=[],
    excludes=excludes,
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=None,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=None)

# 可执行文件配置
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    name='shadowverse_auto_ui',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    console=True,  # 是否启用控制台窗口，因为程序需要获取用户输入以确认同意声明
    icon=os.path.join(project_root, 'app_icon.ico') if os.path.exists(os.path.join(project_root, 'app_icon.ico')) else None,
)

# 收集所有文件
coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=True,
    upx_exclude=[],
    name='shadowverse_auto_ui',
)

print("打包配置说明:")
print("1. 使用虚拟环境路径: {}".format(venv_path if os.path.exists(venv_path) else "未找到虚拟环境"))
print("2. 已排除的配置文件目录: {}".format(", ".join(excluded_dirs)))
print("3. 包含的核心资源: {}".format(", ".join(core_dirs)))
print("4. 打包完成后，请确保以下目录与可执行文件在同一目录下:")
for dir_name in excluded_dirs:
    print("   - {}".format(dir_name))