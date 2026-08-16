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
- **计算模式选择**：支持 Fixture 和 Fixture_plus 两种计算模式
- **参数配置**：可配置采样率、负载阻抗、校准常数、增益等参数

## 核心模块

### 1. Waveform_plugin.py

- 主插件类 (v3)，基于 PyQt6 实现 GUI 界面
- 处理用户交互，调用其他模块进行数据处理和分析
- 实现波形显示窗口和频谱分析窗口

### 2. FFT.py

- 实现 FFT 分析功能，包括窗函数、频谱计算、dBm 转换等
- 使用 scipy.fft 进行 FFT 计算，性能更优
- 支持多种窗函数和计算模式

### 3. fft_processor.py + fft_processor (C 可执行文件)

- C 语言加速的 FFT 处理封装，不依赖 scipy
- 全部 FFT 与频谱算法在 C 代码中完成，性能更高
- 三种能力：
  - `generate_amplitude_csv()` — Bin 文件直接解码为单列电压幅值 CSV
  - `generate_fft_csv()` — 按频率范围生成三列 CSV（频率/幅值/dbm），含加窗 FFT + 二次插值
  - `get_frequency_info()` — 返回基频/RMS/THD/THD+N 等完整频谱信息
- 支持命令行直接调用：
  ```bash
  python fft_processor.py csv  <输入.bin> <输出.csv> <采样率> <窗类型> <增益>
  python fft_processor.py freq <输入.bin> <目标频率Hz> <采样率> <窗类型> <增益>
  python fft_processor.py fft  <输入.bin> <输出.csv> <采样率> <窗类型> <增益> <start> <step> <end>
  ```
- 窗类型：0 矩形 / 1 平顶 / 2 汉宁 / 3 布莱克曼-哈里斯 / 4 Nuttall
- C 源码位于项目根目录 `C/` 文件夹

### 4. code_to_mvolt.py

- 实现 bin 文件解析功能，将二进制数据转换为电压值
- 提供频率计算功能，根据电压数据计算信号频率

### 5. main.ui

- Qt Designer 界面文件，定义应用程序的界面布局和控件

## 项目结构

```
Waveform_plugin/
├── Waveform_plugin.py   # 主插件类 (v3)
├── FFT.py               # FFT 分析模块 (scipy)
├── fft_processor.py     # C 加速 FFT 封装
├── fft_processor        # C 编译的可执行文件
├── code_to_mvolt.py     # Bin→CSV 数据转换模块
├── main.ui              # Qt Designer 界面文件
├── dbm.png              # 频谱分析示例图
├── requirements.txt     # 插件依赖
└── readme.md            # 项目说明文档
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
- **C 加速可选**：fft_processor 可执行文件提供更高性能的 FFT 计算，不依赖 scipy
- **多窗函数支持**：提供多种窗函数选择（矩形/平顶/汉宁/布莱克曼-哈里斯/Nuttall），适应不同的分析需求
- **多种计算模式**：支持 Fixture 和 Fixture_plus 两种计算模式，灵活适应不同场景
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
python3 -m PyQt6.uic.pyuic main.ui -o ui_main.py
```

### 重新编译 C 加速模块

fft_processor 的 C 源码位于项目根目录 `C/` 文件夹，修改后需重新编译：

```bash
cd /path/to/MIX-test/C
gcc -O2 -o ../plugins/Waveform_plugin/fft_processor fft_processor.c -lm
```

## 版本历史

- v3: 集成 C 加速 fft_processor，新增 Nuttall 窗函数，完善 THD/THD+N 计算
- v2: 优化 FFT 计算，增加多种窗函数和计算模式
- v1: 初始版本，基础波形和频谱分析

