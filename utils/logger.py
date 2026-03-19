import logging
import logging.handlers
import os
import datetime

def init_logger(log_file='app.log'):
    """
    初始化日志系统
    """
    # 确保日志目录存在
    log_dir = os.path.dirname(log_file)
    if log_dir and not os.path.exists(log_dir):
        os.makedirs(log_dir)
    
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
            os.rename(log_file, new_log_file)
            print(f"日志文件已超过1MB，已重命名为: {new_log_file}")
    
    logger = logging.getLogger("AppLogger")
    logger.setLevel(logging.DEBUG)
    
    # 清除现有处理器
    for handler in logger.handlers[:]:
        logger.removeHandler(handler)
    
    # 添加文件处理器
    handler = logging.handlers.RotatingFileHandler(log_file, mode='a', maxBytes=5*1024*1024, backupCount=5)
    handler.setLevel(logging.DEBUG)
    formatter = logging.Formatter('%(asctime)s %(filename)s:%(lineno)s > %(message)s', datefmt='%Y/%m/%d %H:%M:%S')
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    
    # 添加控制台处理器
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)
    
    return logger

# 创建全局日志实例
logger = init_logger()