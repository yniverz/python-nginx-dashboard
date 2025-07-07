from dataclasses import dataclass
import dataclasses
import json
import time
from typing import Any, Type



@dataclass
class FRPSWebserver:
    addr: str
    port: int
    user: str
    password: str

    def generate_config_toml(self) -> str:
        return f"""
[webServer]
addr = "{self.addr}"
port = {self.port}
user = "{self.user}"
password = "{self.password}"
"""

@dataclass
class FRPServer:
    id: str
    host: str
    bind_port: int
    auth_token: str
    webserver: FRPSWebserver = None
    last_request: int = 0

    def __post_init__(self):
        self.last_request = 0

    def generate_config_toml(self) -> str:
        config = f"""
bindPort = {self.bind_port}

[auth]
method = "token"
token = "{self.auth_token}"
additionalScopes = [ "HeartBeats",]
"""
        if self.webserver:
            config += self.webserver.generate_config_toml()
        return config.strip()
    
    def was_requested(self):
        self.last_request = int(time.time())

    def is_online(self) -> bool:
        """
        Check if the server was requested in the last 5 minutes.
        """
        return (int(time.time()) - self.last_request) < 120

@dataclass
class FRPConnection:
    name: str
    type: str
    localIP: str
    localPort: int
    remotePort: int
    flags: list[str] = dataclasses.field(default_factory=lambda: ["transport.useEncryption = true"])
    active: bool = True

    def generate_config_toml(self) -> str:
        if not self.active:
            return ""
        config = f"""
[[proxies]]
name = "{self.name}"
type = "{self.type}"
localIP = "{self.localIP}"
localPort = {self.localPort}
remotePort = {self.remotePort}
"""
        for flag in self.flags:
            config += f"{flag}\n"

        return config.strip()

@dataclass
class FRPClient:
    id: str
    server: FRPServer
    connections: list[FRPConnection] = dataclasses.field(default_factory=list)
    last_request: int = 0

    def __post_init__(self):
        self.last_request = 0

    def generate_config_toml(self) -> str:
        config = f"""
serverAddr = "{self.server.host}"
serverPort = {self.server.bind_port}

[auth]
method = "token"
token = "{self.server.auth_token}"
additionalScopes = ["HeartBeats"]
"""
        for connection in self.connections:
            config += connection.generate_config_toml() + "\n"

        return config.strip()
    
    def was_requested(self):
        self.last_request = int(time.time())

    def is_online(self) -> bool:
        """
        Check if the server was requested in the last 5 minutes.
        """
        return (int(time.time()) - self.last_request) < 120





class DataclassJSONEncoder(json.JSONEncoder):
    """
    Recursively adds a __type__ key to all dataclass instances,
    including nested ones like proxies inside clients.
    """
    def default(self, obj: Any) -> Any:
        if dataclasses.is_dataclass(obj):
            return self._encode_dataclass(obj)
        return super().default(obj)

    def _encode_dataclass(self, obj: Any) -> dict:
        result = {"__type__": obj.__class__.__name__}
        for field in dataclasses.fields(obj):
            value = getattr(obj, field.name)
            result[field.name] = self._encode_value(value)
        return result

    def _encode_value(self, value: Any) -> Any:
        if dataclasses.is_dataclass(value):
            return self._encode_dataclass(value)
        elif isinstance(value, list):
            return [self._encode_value(v) for v in value]
        elif isinstance(value, dict):
            return {k: self._encode_value(v) for k, v in value.items()}
        else:
            return value


class DataclassJSONDecoder(json.JSONDecoder):
    """
    Recreates nested dataclasses automatically via object_hook.
    """
    _registry: dict[str, Type] = {
        "FRPSWebserver": FRPSWebserver,
        "FRPServer": FRPServer,
        "FRPConnection": FRPConnection,
        "FRPClient": FRPClient,
    }

    def __init__(self, *args, **kwargs):
        super().__init__(object_hook=self._hook, *args, **kwargs)

    def _hook(self, obj: dict) -> Any:
        cls_name = obj.pop("__type__", None)
        if cls_name is not None:
            cls = self._registry.get(cls_name)
            if cls is None:
                raise ValueError(f"Unknown dataclass type: {cls_name}")
            # The inner objects (if any) have already been processed
            return cls(**obj)
        return obj



@dataclass
class FRPManagerDataStore:
    servers: list[FRPServer] = None
    clients: list[FRPClient] = None

    def __post_init__(self):
        if self.servers is None:
            self.servers = []
        if self.clients is None:
            self.clients = []

    def add_server(self, server: FRPServer):
        if any(s.id == server.id for s in self.servers):
            raise ValueError(f"Server with ID {server.id} already exists.")
        self.servers.append(server)

    def add_client(self, client: FRPClient):
        self.clients.append(client)

    def to_json_file(self, path: str):
        with open(path, 'w') as f:
            json.dump(self.__dict__, f, cls=DataclassJSONEncoder)

    def from_json_file(self, path: str):
        try:
            with open(path, 'r') as f:
                data: dict = json.load(f, cls=DataclassJSONDecoder)
                self.servers = data.get('servers', [])
                self.clients = data.get('clients', [])
        except FileNotFoundError:
            print(f"Configuration file {path} not found. Using empty datastore.")

class AutoFRPManager:
    def __init__(self, config_path: str):
        self.config_path = config_path

        self.datastore = FRPManagerDataStore()
        self.datastore.from_json_file(self.config_path)

    def save_config(self):
        self.datastore.to_json_file(self.config_path)

    def get_server_list(self) -> list[dict]:
        # return [s.__dict__ for s in self.datastore.servers]
        return self.datastore.servers
    
    def get_client_list(self) -> list[dict]:
        # return [c.__dict__ for c in self.datastore.clients]
        return self.datastore.clients
    
    def get_connection_list(self) -> list[dict]:
        result = []
        for client in self.datastore.clients:
            for connection in client.connections:
                result.append({
                    "server_id": client.server.id,
                    "client_id": client.id,
                    "connection_name": connection.name,
                    "type": connection.type,
                    "localIP": connection.localIP,
                    "localPort": connection.localPort,
                    "remotePort": connection.remotePort,
                    "flags": connection.flags,
                    "active": connection.active
                })

        result.sort(key=lambda x: (x['server_id'], x['client_id'], x['connection_name']))
        return result

    
    def get_server_by_id(self, server_id: str) -> FRPServer:
        for server in self.datastore.servers:
            if server.id == server_id:
                return server
        raise ValueError(f"Server with ID {server_id} not found.")
    
    def get_client_by_id(self, client_id: str) -> FRPClient:
        for client in self.datastore.clients:
            if client.id == client_id:
                return client
        raise ValueError(f"Client with ID {client_id} not found.")
    
    def get_connection_by_name(self, client_id: str, connection_name: str) -> FRPConnection:
        for client in self.datastore.clients:
            if client.id == client_id:
                for connection in client.connections:
                    if connection.name == connection_name:
                        return connection
        raise ValueError(f"Connection with name {connection_name} not found in client {client_id}.")
    


    def add_server(self, server: FRPServer):
        self.datastore.add_server(server)
        self.save_config()

    def update_server(self, server: FRPServer):
        self.datastore.servers = [s for s in self.datastore.servers if s.id != server.id]
        self.datastore.servers.append(server)
        self.save_config()

    def remove_server(self, server_id: str):
        self.datastore.servers = [s for s in self.datastore.servers if s.id != server_id]
        self.save_config()

    def add_client(self, client: FRPClient):
        self.datastore.add_client(client)
        self.save_config()

    def update_client(self, client: FRPClient):
        self.datastore.clients = [c for c in self.datastore.clients if c.id != client.id]
        self.datastore.clients.append(client)
        self.save_config()

    def remove_client(self, client_id: str):
        self.datastore.clients = [c for c in self.datastore.clients if c.id != client_id]
        self.save_config()

    def add_connection_to_client(self, client_id: str, connection: FRPConnection):
        for client in self.datastore.clients:
            if client.id == client_id:
                client.connections.append(connection)
                self.save_config()
                return
        raise ValueError(f"Client with ID {client_id} not found.")
    
    def update_connection(self, client_id: str, connection: FRPConnection):
        for client in self.datastore.clients:
            if client.id == client_id:
                client.connections = [c for c in client.connections if c.name != connection.name]
                client.connections.append(connection)
                self.save_config()
                return
        raise ValueError(f"Client with ID {client_id} not found.")

    def remove_connection_from_client(self, client_id: str, connection_name: str):
        for client in self.datastore.clients:
            if client.id == client_id:
                client.connections = [c for c in client.connections if c.name != connection_name]
                self.save_config()
                return
        raise ValueError(f"Client with ID {client_id} not found.")
    
    def toggle_connection(self, client_id: str, connection_name: str):
        for client in self.datastore.clients:
            if client.id == client_id:
                for connection in client.connections:
                    if connection.name == connection_name:
                        connection.active = not connection.active
                        self.save_config()
                        return
        raise ValueError(f"Connection with name {connection_name} not found in client {client_id}.")