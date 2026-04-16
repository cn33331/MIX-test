import logging
import logging.handlers
import os
import datetime

def init_logger(name="AppLogger", log_file="app.log"):
    """
    初始化日志系统
    
    Args:
        name: 日志器名称
        log_file: 日志文件名
    """
    # 确保日志目录存在
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
    
    log_file = os.path.join(log_dir, log_file)
    
    # 检查文件大小，如果超过1MB，重命名为带时间戳的文件
    max_size = 1 * 1000 * 1000  # 1MB
    if os.path.exists(log_file):
        file_size = os.path.getsize(log_file)
        if file_size > max_size:
            # 获取当前时间戳
            timestamp = datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
            # 生成新的文件名
            base_name = os.path.splitext(log_file)[0]
            ext = os.path.splitext(log_file)[1]
            new_log_file = f"{base_name}_{timestamp}{ext}"
            # 重命名文件
            try:
                os.rename(log_file, new_log_file)
                print(f"日志文件已超过1MB，已重命名为: {new_log_file}")
            except Exception as e:
                print(f"重命名日志文件失败: {e}")
    
    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)
    
    # 清除现有处理器
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
    
    # 创建日志格式
    formatter = logging.Formatter('%(asctime)s %(filename)s:%(lineno)s > %(message)s', datefmt='%Y/%m/%d %H:%M:%S')
    
    # 添加文件处理器
    try:
        handler = logging.handlers.RotatingFileHandler(log_file, mode='a', maxBytes=5*1024*1024, backupCount=5)
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

# 创建全局日志实例
logger = init_logger()