#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
串口管理核心模块
"""

import serial
import serial.tools.list_ports
import threading
import time
import logging
import logging.handlers
import os
import datetime

class SerialReader(threading.Thread):
    """
    串口数据读取线程
    """
    def __init__(self, ser, callback=None, logger=None):
        super().__init__()
        self.ser = ser
        self.callback = callback or (lambda msg: print(msg))
        self.logger = logger or (lambda msg: print(msg))
        self.running = True
    
    def run(self):
        try:
            while self.running and self.ser.is_open:
                data = self.ser.readline()
                if data:
                    try:
                        text = data.decode('utf-8', errors='replace').strip()
                        self.callback(f"<< {text}")
                        if hasattr(self.logger, 'debug'):
                            self.logger.debug(f"收到数据: {text}")
                    except Exception as e:
                        error_msg = f"解码错误: {str(e)}"
                        self.callback(error_msg)
                        if hasattr(self.logger, 'error'):
                            self.logger.error(error_msg)
        except Exception as e:
            error_msg = f"读取错误: {str(e)}"
            self.callback(error_msg)
            if hasattr(self.logger, 'error'):
                self.logger.error(error_msg)
    
    def stop(self):
        self.running = False

class UartManager:
    """
    串口管理类
    """
    def __init__(self, callback=None, log_file=None):
        """
        初始化串口管理器
        
        Args:
            callback: 数据接收回调函数，接收一个字符串参数
            log_file: 日志文件路径，如果为None则使用默认路径
        """
        self.ser = None
        self.reader_thread = None
        self.callback = callback or (lambda msg: print(msg))
        self.log_file = log_file
        self.logger = self._init_logger()
    
    def _init_logger(self):
        """
        初始化日志系统
        """
        # 确保日志目录存在
        if self.log_file:
            log_dir = os.path.dirname(self.log_file)
        else:
            if os.name == 'posix':  # macOS or Linux
                # 使用用户主目录下的日志目录
                home_dir = os.path.expanduser('~')
                log_dir = os.path.join(home_dir, '.MIX-Tool', 'logs')
            elif os.name == 'nt':  # Windows
                # 使用AppData目录
                log_dir = os.path.join(os.environ.get('APPDATA', ''), 'MIX-Tool', 'logs')
            else:
                # 其他系统使用当前目录
                log_dir = os.path.join(os.path.dirname(__file__), '..', 'logs')
        
        # 确保日志目录存在
        if not os.path.exists(log_dir):
            try:
                os.makedirs(log_dir)
                print(f"创建日志目录: {log_dir}")
            except Exception as e:
                print(f"创建日志目录失败: {e}")
                # 如果创建失败，使用当前目录
                log_dir = os.path.dirname(__file__)
        
        if not self.log_file:
            self.log_file = os.path.join(log_dir, 'uart.log')
        
        # 检查文件大小，如果超过1MB，重命名为带时间戳的文件
        max_size = 1 * 1000 * 1000  # 1MB
        if os.path.exists(self.log_file):
            file_size = os.path.getsize(self.log_file)
            if file_size > max_size:
                # 获取当前时间戳
                timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
                # 生成新的文件名
                base_name = os.path.splitext(self.log_file)[0]
                ext = os.path.splitext(self.log_file)[1]
                new_log_file = f"{base_name}_{timestamp}{ext}"
                # 重命名文件
                try:
                    os.rename(self.log_file, new_log_file)
                    print(f"日志文件已超过1MB，已重命名为: {new_log_file}")
                except Exception as e:
                    print(f"重命名日志文件失败: {e}")
        
        logger = logging.getLogger("UartLogger")
        logger.setLevel(logging.DEBUG)
        
        # 清除现有处理器
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)
        
        # 创建日志格式
        formatter = logging.Formatter('%(asctime)s %(filename)s:%(lineno)s > %(message)s', datefmt='%Y/%m/%d %H:%M:%S')
        
        # 添加文件处理器
        try:
            handler = logging.handlers.RotatingFileHandler(self.log_file, mode='a', maxBytes=5*1024*1024, backupCount=5)
            handler.setLevel(logging.DEBUG)
            handler.setFormatter(formatter)
            logger.addHandler(handler)
        except Exception as e:
            print(f"添加文件处理器失败: {e}")
        
        # 添加控制台处理器
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(formatter)
        logger.addHandler(console_handler)
        
        return logger
    
    def scan_ports(self):
        """
        扫描系统中所有可用的串口
        
        Returns:
            list: 串口列表，每个元素为 (port, desc) 元组
        """
        ports = []
        try:
            self.logger.info("开始扫描串口...")
            port_list = serial.tools.list_ports.comports()
            for port, desc, hwid in sorted(port_list):
                ports.append((port, desc))
                self.logger.debug(f"发现串口: {port} - {desc}")
            self.logger.info(f"扫描完成，找到 {len(ports)} 个串口")
        except Exception as e:
            error_msg = f"扫描串口失败: {str(e)}"
            self.callback(error_msg)
            self.logger.error(error_msg)
        return ports
    
    def connect(self, port, baudrate=115200, data_bits=8, parity='N', stop_bits=1):
        """
        连接串口
        
        Args:
            port: 串口路径
            baudrate: 波特率
            data_bits: 数据位 (5-8)
            parity: 校验位 ('N', 'O', 'E', 'M', 'S')
            stop_bits: 停止位 (1, 1.5, 2)
        
        Returns:
            bool: 连接是否成功
        """
        try:
            self.logger.info(f"尝试连接串口: {port} @ {baudrate}, {data_bits}{parity}{stop_bits}")
            
            # 映射数据位
            data_bits_map = {
                5: serial.FIVEBITS,
                6: serial.SIXBITS,
                7: serial.SEVENBITS,
                8: serial.EIGHTBITS
            }
            bytesize = data_bits_map.get(data_bits, serial.EIGHTBITS)
            
            # 映射校验位
            parity_map = {
                'N': serial.PARITY_NONE,
                'O': serial.PARITY_ODD,
                'E': serial.PARITY_EVEN,
                'M': serial.PARITY_MARK,
                'S': serial.PARITY_SPACE
            }
            parity = parity_map.get(parity.upper(), serial.PARITY_NONE)
            
            # 映射停止位
            stop_bits_map = {
                1: serial.STOPBITS_ONE,
                1.5: serial.STOPBITS_ONE_POINT_FIVE,
                2: serial.STOPBITS_TWO
            }
            stopbits = stop_bits_map.get(stop_bits, serial.STOPBITS_ONE)
            
            # 连接串口
            self.ser = serial.Serial(
                port=port,
                baudrate=baudrate,
                bytesize=bytesize,
                parity=parity,
                stopbits=stopbits,
                timeout=1
            )
            
            if self.ser.is_open:
                success_msg = f"✅ 串口连接成功: {port} @ {baudrate}"
                self.callback(success_msg)
                self.logger.info(success_msg)
                
                # 启动读取线程
                self.reader_thread = SerialReader(self.ser, self.callback, self.logger)
                self.reader_thread.daemon = True
                self.reader_thread.start()
                self.logger.info("串口读取线程已启动")
                return True
            else:
                error_msg = "❌ 串口连接失败: 无法打开串口"
                self.callback(error_msg)
                self.logger.error(error_msg)
                return False
        except Exception as e:
            error_msg = f"❌ 连接失败: {str(e)}"
            self.callback(error_msg)
            self.logger.error(error_msg)
            return False
    
    def disconnect(self):
        """
        断开串口连接
        """
        self.logger.info("开始断开串口连接...")
        
        if self.reader_thread:
            self.reader_thread.stop()
            self.reader_thread.join(timeout=1.0)
            self.reader_thread = None
            self.logger.info("串口读取线程已停止")
        
        if self.ser and self.ser.is_open:
            self.ser.close()
            self.logger.info("串口已关闭")
        
        self.ser = None
        success_msg = "✅ 串口已断开"
        self.callback(success_msg)
        self.logger.info(success_msg)
    
    def is_connected(self):
        """
        检查串口是否已连接
        
        Returns:
            bool: 是否已连接
        """
        return self.ser is not None and self.ser.is_open
    
    def write(self, data, add_newline=True):
        """
        写入数据到串口
        
        Args:
            data: 要写入的数据
            add_newline: 是否添加换行符
        
        Returns:
            bool: 写入是否成功
        """
        if not self.is_connected():
            error_msg = "❌ 写入失败: 串口未连接"
            self.callback(error_msg)
            self.logger.error(error_msg)
            return False
        
        try:
            if add_newline:
                data_to_send = data + '\n'
            else:
                data_to_send = data
            
            self.logger.info(f"写入数据: {data}")
            self.ser.write(data_to_send.encode('utf-8'))
            self.callback(f">> {data}")
            self.logger.debug(f"数据写入成功: {data}")
            return True
        except Exception as e:
            error_msg = f"写入失败: {str(e)}"
            self.callback(error_msg)
            self.logger.error(error_msg)
            return False
    
    def read(self, size=1, timeout=None):
        """
        从串口读取数据
        
        Args:
            size: 要读取的字节数
            timeout: 超时时间（秒）
        
        Returns:
            bytes: 读取的数据
        """
        if not self.is_connected():
            error_msg = "❌ 读取失败: 串口未连接"
            self.callback(error_msg)
            self.logger.error(error_msg)
            return b''
        
        try:
            # 保存原始超时设置
            original_timeout = self.ser.timeout
            
            # 设置新的超时
            if timeout is not None:
                self.ser.timeout = timeout
            
            data = self.ser.read(size)
            
            # 恢复原始超时设置
            if timeout is not None:
                self.ser.timeout = original_timeout
            
            if data:
                self.logger.debug(f"读取到数据: {data}")
            
            return data
        except Exception as e:
            error_msg = f"读取失败: {str(e)}"
            self.callback(error_msg)
            self.logger.error(error_msg)
            return b''
    
    def readline(self, timeout=None):
        """
        从串口读取一行数据
        
        Args:
            timeout: 超时时间（秒）
        
        Returns:
            str: 读取的字符串
        """
        if not self.is_connected():
            error_msg = "❌ 读取失败: 串口未连接"
            self.callback(error_msg)
            self.logger.error(error_msg)
            return ""
        
        try:
            # 保存原始超时设置
            original_timeout = self.ser.timeout
            
            # 设置新的超时
            if timeout is not None:
                self.ser.timeout = timeout
            
            data = self.ser.readline()
            
            # 恢复原始超时设置
            if timeout is not None:
                self.ser.timeout = original_timeout
            
            if data:
                text = data.decode('utf-8', errors='replace').strip()
                self.logger.debug(f"读取到一行数据: {text}")
                return text
            else:
                return ""
        except Exception as e:
            error_msg = f"读取失败: {str(e)}"
            self.callback(error_msg)
            self.logger.error(error_msg)
            return ""
    
    def send(self, data, timeout=1.0, expect_response=False):
        """
        发送数据
        
        Args:
            data: 要发送的数据
            timeout: 等待响应的超时时间（秒）
            expect_response: 是否期望响应
        
        Returns:
            tuple: (bool, str) - (发送是否成功, 响应数据)
        """
        if not self.is_connected():
            error_msg = "❌ 发送失败: 串口未连接"
            self.callback(error_msg)
            self.logger.error(error_msg)
            return False, ""
        
        try:
            self.logger.info(f"发送数据: {data}")
            self.ser.write((data + '\n').encode('utf-8'))
            self.callback(f">> {data}")
            self.logger.debug(f"数据发送成功: {data}")
            
            # 如果期望响应，等待并读取
            response = ""
            if expect_response:
                response = self.readline(timeout=timeout)
                if response:
                    self.callback(f"<< {response}")
                    self.logger.info(f"收到响应: {response}")
                else:
                    self.logger.warning("未收到响应")
            
            return True, response
        except Exception as e:
            error_msg = f"发送失败: {str(e)}"
            self.callback(error_msg)
            self.logger.error(error_msg)
            return False, ""