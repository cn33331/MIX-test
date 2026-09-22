# MIX_2.0 RPC 协议注册机制详解

## 概述

MIX_2.0 协议使用 ZeroMQ 的 DEALER-ROUTER 模式实现 RPC 通信。客户端需要通过特定的注册流程才能使用业务服务。

## 架构说明

### 通信模式

```
┌─────────────────────────────────────────────────────────────────┐
│                 DEALER-ROUTER 通信模式                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                 │
│  ┌──────────┐                              ┌──────────┐         │
│  │  Client  │                              │  Server  │         │
│  │  (DEALER)│                              │ (ROUTER) │         │
│  └────┬─────┘                              └────┬─────┘         │
│       │                                         │                │
│       │────── ZMQ 自动生成客户端ID ──────────>│                │
│       │      (route_id: b'\x00k\x86E\xad')   │                │
│       │                                         │                │
│       │────── 注册请求 ─────────────────────>│                │
│       │      hello("MIX8D")                   │                │
│       │                                         │                │
│       │<───── 注册成功响应 ──────────────────│                │
│       │      {status: success}                │                │
│       │                                         │                │
│       │────── 业务请求 ─────────────────────>│                │
│       │      power.measure(...)               │                │
│       │                                         │                │
│       │<───── 业务响应 ─────────────────────│                │
│       │      {result: {...}}                  │                │
│                                                                 │
└─────────────────────────────────────────────────────────────────┘
```

### 客户端ID生成

客户端ID由 ZeroMQ 自动生成，格式为二进制字节串：

```python
# 示例
b'\x00k\x86E\xad'
b'\x00800041a8'
```

**特性**：
- 每次连接生成不同的随机ID
- 用于 ROUTER 识别不同的客户端连接
- 二进制格式，高效紧凑

## 注册流程

### 完整时序

```bash
# 步骤1: 获取服务器版本（连接测试）
{"id":"B9B12914FB1C47C1A8225F93A58629D9","method":"version","remote_id":"__server__"}

# 响应
{"version": "MIX_2.0", "request_id": "B9B12914FB1C47C1A8225F93A58629D9", "result": "3.0.0"}

# 步骤2: 注册客户端身份
{"args":["MIX8D"],"id":"904AA867CF54460989D7D071EEE034EC","method":"hello","remote_id":"__MIX_CLIENT_MANAGER__"}

# 响应
{"version": "MIX_2.0", "request_id": "904AA867CF54460989D7D071EEE034EC", "result": {"status": "success", "session_id": "test_session"}}

# 步骤3: 获取所有服务
{"id":"AF344CD74FBA4114BF617E0CA64B763C","method":"get_all_services","remote_id":"__server__"}

# 步骤4: 查询具体服务信息
{"args":["power"],"id":"9080C0E772F54FDBAFE8E524B7C18B7E","method":"get_service_info","remote_id":"__server__"}
```

### 注册请求格式

```json
{
    "version": "MIX_2.0",
    "id": "请求UUID",
    "remote_id": "__MIX_CLIENT_MANAGER__",
    "method": "hello",
    "args": ["MIX8D"]
}
```

| 字段 | 值 | 说明 |
|------|-----|------|
| remote_id | `__MIX_CLIENT_MANAGER__` | 客户端管理器服务 |
| method | `hello` | 注册方法 |
| args | `["MIX8D"]` | 客户端身份标识 |

### 注册响应格式

```json
{
    "version": "MIX_2.0",
    "request_id": "请求UUID",
    "result": {
        "status": "success",
        "session_id": "test_session"
    }
}
```

## 服务端实现

### ClientManager 核心代码

在 `rpc_8/mix/rpc/server/clientmanager.py` 中实现：

#### 1. 客户端对象表示

```python
class ClientProxy(object):
    """代表一个客户端连接"""
    def __init__(self, route_id, identity):
        self.route_id = route_id    # ZMQ 生成的客户端ID
        self.identity = identity     # 客户端身份（如 "MIX8D"）
        self.last_update = time.time()  # 最后活跃时间
        self.event_listener = None
        self.event_sources = []

    def idle_too_long(self):
        """检查客户端是否空闲超时"""
        return (time.time() - self.last_update) > constants.CLIENT_DORMANT_MAX
```

#### 2. 注册处理逻辑

```python
def handle_client_request(self, client_route, request_msg):
    """处理客户端管理器请求"""
    request = self.protocol.parse_request(request_msg)

    if request.method == constants.MIX_CLIENT_HELLO:
        # 提取客户端身份
        identity = request.args[0]

        # 创建 ClientProxy 并注册到字典
        self.clients[client_route] = ClientProxy(client_route, identity)

        # 返回响应
        response = self.protocol.create_response(request.id, self.server.session_id)

        self.logger.info(f'new client {identity} appeared')

        # 清理旧客户端
        self.purge()

    elif request.method == constants.MIX_CLIENT_BYE:
        # 处理客户端断开
        client_proxy = self.clients[client_route]
        client_proxy.release()
        self.clients.pop(client_route)
        self.logger.info(f'client {client_proxy.identity} says bye')
```

#### 3. 请求分发验证

```python
def dispatch(self):
    """分发请求到对应的服务"""
    client, target, msg = self.transport.recv()
    service_id = target.decode('utf8')

    if service_id == constants.MIX_CLIENT_MANAGER:
        # 客户端管理器请求（不需要验证注册）
        response = self.handle_client_request(client, msg)

    elif service_id == '__server__':
        # 服务器服务请求（不需要验证注册）
        request = self.protocol.parse_request(msg)
        response = self.handle_request(request, self.server)

    else:
        # 业务服务请求（需要验证注册）
        if c_proxy := self.clients.get(client):
            # 客户端已注册，更新活跃时间
            c_proxy.last_update = time.time()
            self.worker_man.handle_request(client, service_id, msg)
        else:
            # 未注册客户端！返回错误
            error_msg = f'unregistered client {client}. This may be a spurious ' \
                        'message from a previous session'
            request = self.protocol.parse_request(msg)
            response = self.protocol.error_response(
                request.id,
                constants.INVALID_REQUEST_ERROR,  # -32600
                error_msg
            )

    # 发送响应
    if response:
        self.transport.send(client, response.serialize())
```

## 错误码

| 错误码 | 含义 | 说明 |
|--------|------|------|
| -32600 | Invalid Request | 无效请求（未注册客户端） |
| -32603 | Internal error | 服务器内部错误 |

## 常见问题

### 1. "unregistered client" 错误

**原因**：
- 客户端ID已生成，但未调用 `hello` 方法注册
- 注册请求和业务请求到达顺序颠倒
- 服务端清理了超时客户端

**解决方案**：
```python
def send_request(self, remote_id, method, params):
    # 确保已注册
    if remote_id not in ["__server__", "__MIX_CLIENT_MANAGER__"]:
        if not self._registered:
            self.stub("__MIX_CLIENT_MANAGER__", "hello", "MIX8D")
            self._registered = True

    # 发送业务请求
    return self._send_request(remote_id, method, params)
```

### 2. 客户端ID格式

客户端ID是 ZeroMQ 自动生成的二进制格式：

| 表示 | 示例 |
|------|------|
| 二进制 | `b'\x00k\x86E\xad'` |
| 十六进制 | `006b8645ad` |

### 3. 会话残留消息

服务端可能会收到前一个会话的残留消息：

```
unregistered client b'\x00k\x86E\xad'. This may be a spurious message from a previous session
```

**处理方式**：忽略并返回错误，让客户端重新注册。

## 关键常量

在 `rpc_8/mix/rpc/util/constants.py` 中定义：

```python
MIX_CLIENT_MANAGER = "__MIX_CLIENT_MANAGER__"
MIX_CLIENT_HELLO = "hello"
MIX_CLIENT_BYE = "bye"
INVALID_REQUEST_ERROR = -32600
CLIENT_DORMANT_MAX = 300  # 客户端最大空闲时间（秒）
```

## 总结

1. **注册必要性**：除了 `__server__` 和 `__MIX_CLIENT_MANAGER__` 服务外，所有业务服务都需要客户端先注册
2. **注册时机**：连接成功后立即注册，然后再发送业务请求
3. **ID管理**：客户端ID由ZeroMQ自动生成，服务端维护已注册客户端字典
4. **超时清理**：服务端定期清理空闲超时的客户端连接
