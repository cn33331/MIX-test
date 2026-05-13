# Waveform\_plugin 波形分析插件

## 项目概述

Waveform\_plugin 是一个基于 PyQt6 开发的信号分析工具插件，主要用于处理和分析电压信号数据，支持 bin 文件解析、CSV 数据分析、FFT 频谱分析以及波形可视化等功能。该插件作为 Automation-Platform 的子模块运行。

## 主要功能

### 1. 文件解析

- **Bin 文件解析**：将二进制数据文件解析为 CSV 格式的电压数据
- **CSV 文件分析**：读取和分析 CSV 格式的电压数据

### 2. 信号分析

- **频率计算**：根据电压数据计算信号频率
- **FFT 频谱分析**：对电压信号进行快速傅里叶变换，分析频谱特性
- **dBm 计算**：将电压幅值转换为 dBm 功率值，支持多种计算方法

### 3. 数据可视化

- **电压波形图**：显示指定区间的电压波形（使用 PyQt6 QPainter 绘制）
- **频谱分析图**：显示频率与功率的关系图，标记目标频率或峰值

### 4. 配置选项

- **窗函数选择**：支持无窗、平顶窗、汉宁窗、布莱克曼-哈里斯窗
- **计算模式选择**：支持 Apple 和 Fixture 两种计算模式
- **参数配置**：可配置采样率、负载阻抗、校准常数、增益等参数

## 核心模块

### 1. Waveform\_plugin.py

- 主插件类，基于 PyQt6 实现 GUI 界面
- 处理用户交互，调用其他模块进行数据处理和分析
- 实现波形显示窗口和频谱分析窗口

### 2. FFT.py

- 实现 FFT 分析功能，包括窗函数、频谱计算、dBm 转换等
- 使用 scipy.fft 进行 FFT 计算，性能更优
- 支持多种窗函数和计算模式

### 3. code\_to\_mvolt.py

- 实现 bin 文件解析功能，将二进制数据转换为电压值
- 提供频率计算功能，根据电压数据计算信号频率

### 4. ui/main.py

- 由 Qt Designer 生成的 UI 界面代码
- 定义应用程序的界面布局和控件

## 项目结构

```
Waveform_plugin/
├── Waveform_plugin.py   # 主插件类
├── FFT.py               # FFT 分析模块
├── FFT_debug.py         # FFT 调试模块
├── code_to_mvolt.py     # 数据转换模块
├── ui/                  # UI 界面文件夹
│   ├── __init__.py
│   ├── main.py          # 生成的 UI 代码
│   └── main.ui          # Qt Designer 界面文件
├── readme.md            # 项目说明文档
└── requirements.txt     # 项目依赖
```

## 安装与运行

### 1. 激活虚拟环境

```bash
source /Users/gdlocal/Desktop/env_sum/vis/bin/activate
```

### 2. 安装依赖

```bash
pip install -r requirements.txt
```

### 3. 运行应用

作为 Automation-Platform 的插件运行，主应用会自动加载该插件。

## 使用方法

1. **解析 Bin 文件**：点击 "解析 Bin 文件" 按钮，选择 bin 文件，系统会自动解析并生成 CSV 文件
2. **分析 CSV 文件**：点击 "解析 CSV 文件" 按钮，选择 CSV 文件，系统会计算频率和 dBm 值
3. **查看电压波形**：设置起始和结束数据点，点击 "生成波形图" 按钮
4. **查看频谱分析**：设置频率范围和步长，点击 "生成 DBM 波形图" 按钮

## 技术特点

- **高性能 FFT**：使用 scipy.fft 进行快速傅里叶变换，性能优异
- **多窗函数支持**：提供多种窗函数选择，适应不同的分析需求
- **多种计算模式**：支持 Apple 和 Fixture 两种计算模式，灵活适应不同场景
- **轻量级可视化**：使用 PyQt6 QPainter 实现自定义绘图，无需 matplotlib
- **用户友好**：支持拖放操作，界面简洁易用
- **跨平台**：基于 PyQt6 开发，支持 Windows、macOS 等平台

## 依赖项

- PyQt6：GUI 界面库
- NumPy：数值计算库
- SciPy：科学计算库（用于 FFT 计算）

## 注意事项

- 确保输入的 bin 文件格式正确，是 32 位小端格式的数据
- CSV 文件应为单列电压数据，无表头
- 采样率设置应与原始数据采集时一致，默认为 125MHz
- 负载阻抗默认为 50Ω，适用于射频场景

## 开发说明

- 使用 Qt Designer 设计界面，保存为 .ui 文件
- 使用 pyuic6 将 .ui 文件转换为 .py 文件
- 导入生成的 UI 类到主应用程序

```bash
python3 -m PyQt6.uic.pyuic ui/main.ui -o ui/main.py
```

