#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""插件依赖扫描与随包校验。

背景
----
``plugins/`` 目录是在 PyInstaller 打包**完成之后**，由 ``Automation-Platform.spec``
的 ``post_build_copy_plugins()`` 以「普通文件」复制进 ``.app`` 的，它**不参与**
PyInstaller 的导入分析。所以插件里 import 的模块，只有在主程序本身也用到、或者构建
环境偶然把依赖链条带进来时才会进入产物；否则插件会在运行时抛 ModuleNotFoundError。

真实事故
--------
``plugins/i2c_scan_plugin/transports.py`` 顶层写了
``from concurrent.futures import ThreadPoolExecutor``，而主程序从不使用 concurrent。
x86_64 runner 的依赖图恰好（经由 setuptools/pkg_resources 链条）把
``concurrent.futures`` 带了进来，arm64 runner 没有 → arm64 产物一打开就报
「i2c_scan_plugin 缺少 concurrent」。同一份代码、同一次 CI，两个架构一个好一个坏。

做法
----
从 ``plugins/plugins.json`` 声明的插件入口出发，沿「插件内部 import 图」做可达性
遍历（只走插件目录内的文件，因此没人引用的遗留文件不会被算进来），收集插件真正
用到的外部模块：

    python plugin_deps.py --list                  # 打印可达的外部模块（spec 用它生成 hiddenimports）
    python plugin_deps.py --check <app 主程序>     # 校验产物里这些模块是否都在

``--check`` 退出码非 0 时 CI 会失败，从而拦住「能构建、但插件一用就崩」的产物。
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import sys


def _py_files(root: str):
    """递归列出 root 下的 .py（跳过 __pycache__）。"""
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d != '__pycache__']
        for fn in filenames:
            if fn.endswith('.py'):
                yield os.path.join(dirpath, fn)


def plugin_entries(base_dir: str):
    """按 plugins.json 的声明解析插件入口文件。"""
    manifest = os.path.join(base_dir, 'plugins', 'plugins.json')
    if not os.path.exists(manifest):
        return []
    with open(manifest, encoding='utf-8') as fh:
        names = json.load(fh).get('plugins', [])
    entries = []
    for name in names:
        for cand in (os.path.join('plugins', f'{name}_plugin', f'{name}_plugin.py'),
                     os.path.join('plugins', f'{name}_plugin.py')):
            full = os.path.join(base_dir, cand)
            if os.path.exists(full):
                entries.append(full)
                break
    return entries


def collect(base_dir: str = '.'):
    """返回 (外部模块 -> 引用它的文件集合, 可达文件集合)。

    只把「插件目录内独立成文件」的模块视为内部模块；其余一律算外部依赖。
    """
    plugins_dir = os.path.join(base_dir, 'plugins')
    index = {}
    # 插件用绝对 import（运行时把插件目录加进 sys.path），所以按文件名建索引
    for path in _py_files(plugins_dir):
        index.setdefault(os.path.basename(path)[:-3], path)
    # 插件目录下的子目录也是包（如 plugins/utils、plugins/libs、plugins/MIX_debug_plugin/mix），
    # 它们同样会随 plugins/ 一起被复制进 app，不算外部依赖
    for dirpath, dirnames, filenames in os.walk(plugins_dir):
        dirnames[:] = [d for d in dirnames if d != '__pycache__']
        if os.path.abspath(dirpath) == os.path.abspath(plugins_dir):
            continue
        if any(f.endswith('.py') for f in filenames):
            index.setdefault(os.path.basename(dirpath), dirpath)

    seen, external = set(), {}

    def visit(path):
        if path in seen:
            return
        seen.add(path)
        if os.path.isdir(path):              # 包：其下所有 .py 都会随包
            for f in _py_files(path):
                visit(f)
            return
        try:
            with open(path, encoding='utf-8', errors='replace') as fh:
                tree = ast.parse(fh.read())
        except SyntaxError:
            return
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    top = alias.name.split('.')[0]
                    if top in index:
                        visit(index[top])
                    else:
                        # 记录完整点分路径（如 concurrent.futures）——
                        # 只记顶层名会漏掉子模块，而子模块才是真正被 import 的东西
                        external.setdefault(alias.name, set()).add(path)
            elif isinstance(node, ast.ImportFrom):
                top = (node.module or '').split('.')[0]
                if not top:
                    continue
                if top in index:
                    visit(index[top])
                else:
                    external.setdefault(node.module, set()).add(path)

    for entry in plugin_entries(base_dir):
        visit(os.path.abspath(entry))
    return external, seen


def external_modules(base_dir: str = '.'):
    """插件可达的外部（非插件内）模块名，已排序。"""
    external, _ = collect(base_dir)
    return sorted(external)


def bundle_modules(binary: str):
    """产物内可被 import 的模块集合（完整点分路径）。

    来源：PYZ（纯 Python）+ base_library.zip（引导期冻结库，内容是 .pyc）+
    外层扩展模块（.so/.dylib）+ 解释器内建模块。

    注意这里只收完整路径、不做"顶层包名也算"的宽松处理：
    产物里有 ``concurrent``（包的 __init__）并不代表 ``concurrent.futures``
    子模块可用，而插件 import 的恰恰是后者。
    """
    import io
    import zipfile

    from PyInstaller.archive.readers import CArchiveReader

    available = set(sys.builtin_module_names)
    archive = CArchiveReader(binary)
    for name in archive.toc:
        if name.endswith('.pyz'):
            available |= set(archive.open_embedded_archive(name).toc)
    if 'base_library.zip' in archive.toc:
        with zipfile.ZipFile(io.BytesIO(archive.extract('base_library.zip'))) as zf:
            for name in zf.namelist():
                available.add(name.rsplit('.', 1)[0].replace('/', '.'))
    for name in archive.toc:
        base = os.path.basename(name)
        if not base.endswith(('.so', '.dylib')):
            continue
        # 扩展模块在归档里是路径形式（PyQt6/QtCore.abi3.so、zmq/_zmq.cpython-310-darwin.so），
        # 要把目录一起换算成点分名，否则 PyQt6.QtCore 这种子模块会被误判为缺失
        directory, filename = os.path.split(name)
        stem = filename.split('.')[0]
        available.add(stem)
        if directory:
            available.add(directory.replace('/', '.') + '.' + stem)
    return available


def check(binary: str, base_dir: str = '.'):
    """校验插件可达依赖是否都在产物里。返回缺失模块列表。"""
    external, reachable = collect(base_dir)
    available = bundle_modules(binary)
    missing = []
    for module in sorted(external):
        if module not in available:
            missing.append((module, sorted(external[module])))
    print(f'插件入口可达文件 {len(reachable)} 个，外部依赖 {len(external)} 个')
    if missing:
        print('\n以下模块插件会用到，但产物中没有：')
        for module, users in missing:
            print(f'  - {module}')
            for user in users:
                print(f'      引用自 {os.path.relpath(user, base_dir)}')
    return missing


def main(argv=None):
    parser = argparse.ArgumentParser(description='插件依赖扫描与随包校验')
    parser.add_argument('--base-dir', default='.', help='仓库根目录（含 plugins/）')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--list', action='store_true', help='打印插件可达的外部模块')
    group.add_argument('--check', metavar='BINARY', help='校验产物主程序是否包含这些模块')
    args = parser.parse_args(argv)

    if args.list:
        for module in external_modules(args.base_dir):
            print(module)
        return 0

    missing = check(args.check, args.base_dir)
    if missing:
        names = ', '.join(m for m, _ in missing)
        print(f'\n::error::插件依赖未随包: {names}')
        print('处理方式：这些模块应由 Automation-Platform.spec 的 hiddenimports 显式声明'
              '（plugin_deps.py --list 的输出会被自动带上），或把插件里未使用的 import 删掉。')
        return 1
    print('\n插件依赖检查通过：全部随包')
    return 0


if __name__ == '__main__':
    sys.exit(main())
