# 多设备配置说明

## 概述

现在支持为不同的设备配置不同的设置，包括截图方法和模板目录。

## 设备配置参数

### screenshot_deep_color
- **类型**: boolean
- **默认值**: false
- **说明**: 控制截图方法
  - `false`: 使用普通截图方法
  - `true`: 使用深色截图方法（提高亮度40）

### is_global
- **类型**: boolean
- **默认值**: false
- **说明**: 控制模板目录选择
  - `false`: 使用 `templates` 文件夹（国服模板）
  - `true`: 使用 `templates_global` 文件夹（国际服模板）

## 配置示例

### 单设备配置
```json
{
  "devices": [
    {
      "name": "MuMu模拟器",
      "serial": "127.0.0.1:16384",
      "screenshot_deep_color": false,
      "is_global": false
    }
  ]
}
```

### 多设备配置
```json
{
  "devices": [
    {
      "name": "MuMu模拟器-国服",
      "serial": "127.0.0.1:16384",
      "screenshot_deep_color": false,
      "is_global": false
    },
    {
      "name": "MuMu模拟器-国际服",
      "serial": "127.0.0.1:16385",
      "screenshot_deep_color": true,
      "is_global": true
    }
  ]
}
```

## 使用场景

### 国服 vs 国际服
- **国服设备**: `is_global: false` → 使用 `templates` 文件夹
- **国际服设备**: `is_global: true` → 使用 `templates_global` 文件夹

### 不同模拟器
- **MuMu模拟器**: 可能需要 `screenshot_deep_color: true`
- **雷电模拟器**: 通常使用 `screenshot_deep_color: false`
- **夜神模拟器**: 可能需要 `screenshot_deep_color: true`

## 日志输出

程序启动时会显示每个设备使用的配置：

```
2025-08-02 21:37:31,314 - Device-127.0.0.1:16384 - INFO - 初始化截图方法: 使用普通截图方法
2025-08-02 21:37:32,151 - INFO - 模板管理器初始化: 使用目录 'templates' (is_global=False)
```

## 目录结构

```
auto_szb/
├── templates/           # 国服模板目录
│   ├── cost_numbers/
│   ├── 国服替换/
│   └── *.png
├── templates_global/    # 国际服模板目录
│   ├── cost_numbers/
│   ├── 国际服替换/
│   └── *.png
└── config.json         # 配置文件
```

## 注意事项

1. **模板目录**: 确保对应的模板目录存在并包含必要的模板文件
2. **设备序列号**: 每个设备的 `serial` 必须唯一
3. **配置验证**: 程序会自动验证配置的有效性
4. **性能优化**: 配置在设备初始化时读取一次，运行时不会重复读取 