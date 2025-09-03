


from app.persistence.models import GatewayClient, GatewayConnection, GatewayServer
from app.persistence import repos


def generate_server_toml(server: GatewayServer) -> dict:
    config = f"""
bindPort = {server.bind_port}

[auth]
method = "token"
token = "{server.auth_token}"
additionalScopes = [ "HeartBeats",]
"""
    return config.strip()
    

def generate_client_toml(db, client: GatewayClient) -> str:
    config = f"""
serverAddr = "{client.server.host}"
serverPort = {client.server.bind_port}

[auth]
method = "token"
token = "{client.server.auth_token}"
additionalScopes = ["HeartBeats"]
"""
    connections = repos.GatewayConnectionRepo(db).list_by_client_id(client.id)

    for connection in connections:
        config += generate_connection_toml(connection) + "\n"

    return config.strip()


def generate_connection_toml(connection: GatewayConnection) -> str:
    if not connection.active:
        return ""
    config = f"""
[[proxies]]
name = "{connection.name}"
type = "{connection.protocol.value}"
localIP = "{connection.local_ip}"
localPort = {connection.local_port}
remotePort = {connection.remote_port}
"""
    for flag in connection.flags:
        config += f"{flag}\n"

    return config.strip()