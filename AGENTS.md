# AGENTS.md

## 快速命令
- 开发启动 GUI：`python main_ui.py`；批处理启动脚本固定为 `conda run -n bydauto pythonw main_ui.py`。
- CLI 入口：`python main.py`，退出时会等待“按回车键退出”。
- 开发/运行依赖按 README 使用锁文件：`pip install -r requirements-py311.lock`；`requirements-build.in` 只用于打包工具。
- 可复现打包：先 `pip install -r requirements-py311.lock`，再 `pip install -r requirements-build.in`，然后 `pyinstaller main.spec`。
- 当前仓库没有发现 pytest/CI/lint/typecheck 配置；做代码级验证优先用 `python -m compileall src main.py main_ui.py`。

## 入口与架构
- `main_ui.py` 和 `main.py` 都是薄入口；启动编排集中在 `src/app/bootstrap.py`。
- 源码入口会先调用 `src/utils/onnxruntime_dll.py`，在 Windows 下优先把当前 Python 环境的 `onnxruntime/capi` DLL 目录加入搜索路径。
- 主要边界：`src/ui` 界面与工作线程，`src/device` 设备管理，`src/game` 战斗/效果/策略，`src/config` 配置与持久化，`src/core` 通用 IO/日志。
- UI 页面在 `src/ui/pages/`；卡牌效果引擎相关实现集中在 `src/game/effects/`、`src/game/policy/`，配套文档见 `docs/effects_user_manual.md` 与 `docs/effects_developer_manual.md`。

## 运行配置与路径陷阱
- `config.json` 是关键运行状态/配置，含设备、策略、模板目录、UI、卡牌特殊效果等；它被 `.gitignore` 忽略，不要把本地运行配置当作可提交默认值。
- 应用根目录由 `src/config/paths.py` 决定：源码运行取项目根，PyInstaller 运行取 exe 所在目录；`config.json` 始终从该根目录解析。
- 免责声明同意状态优先读写应用根目录 `consent.txt`，并可能同步到 `config.json`；不要误以为只看当前工作目录。
- `card_cost` 是当前卡牌费用目录；`shadowverse_cards_cost` 仅作为旧目录迁移来源。

## 打包注意
- `main.spec` 的 PyInstaller 入口是 `main_ui.py`。
- 打包会包含 `models/craft_mlt_25k.pth`、`models/english_g2.pth`、`models/mnist_adv.onnx`、`src/masks/hp_mask.png`、`uiautomator2/assets`、PyQt5 插件和运行 hook `pyi_rth_onnxruntime_dll.py`。
- 打包刻意不内置用户可改资源：`config.json`、`templates/`、`templates_global/`、`card_cost/`、`shadowverse_cards_cost/`、`quanka/`、`Image/`；发布后这些目录需与 exe 同级提供。

## 项目约束
- 识别流程只支持 1280x720 模拟器分辨率。
- 国际服 MuMu 可能有画面过暗导致模板识别失败的问题；README 建议开启深色识别并使用黑色背景场地。
- 图片模板是业务资源：`.gitignore` 全局忽略图片，但显式允许 `templates/`、`templates_global/`、`src/templates/` 下的图片。
