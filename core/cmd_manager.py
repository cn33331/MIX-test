class CommandManager:
    def __init__(self):
        self.commands = {
            'reset': {'service': 'relay', 'method': 'reset'},
            'led_blue': {'service': 'lucifer', 'method': 'led_control', 'params': ['UUT4', 'BLUE']},
            'led_red': {'service': 'lucifer', 'method': 'led_control', 'params': ['UUT4', 'RED']},
            'read_eeprom': {'service': 'eeprom', 'method': 'read_string_eeprom', 'params': [0x20, 30]},
            'write_eeprom': {'service': 'eeprom', 'method': 'write_string_eeprom'}
        }
    
    def get_command(self, cmd_name):
        """
        获取指令配置
        """
        return self.commands.get(cmd_name)
    
    def execute_command(self, rpc_client, cmd_name, *args, **kwargs):
        """
        执行指令
        """
        cmd_config = self.get_command(cmd_name)
        if not cmd_config:
            return f"指令 {cmd_name} 不存在"
        
        service = cmd_config['service']
        method = cmd_config['method']
        params = cmd_config.get('params', [])
        
        # 合并参数
        if args:
            params.extend(args)
        
        return rpc_client.send_command(service, method, *params, **kwargs)