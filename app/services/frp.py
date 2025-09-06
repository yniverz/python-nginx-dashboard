

"""
FRP (Fast Reverse Proxy) configuration generation.
Generates TOML configuration files for FRP servers, clients, and connections.
"""
from app.persistence.models import GatewayClient, GatewayConnection, GatewayServer
from app.persistence import repos


def generate_server_toml(server: GatewayServer) -> str:
    """
    Generate FRP server configuration in TOML format.
    Configures the server to listen on the specified port with token authentication.
    """
    config = f"""
bindPort = {server.bind_port}

[auth]
method = "token"
token = "{server.auth_token}"
additionalScopes = [ "HeartBeats",]
"""
    return config.strip()
    

def generate_client_toml(db, client: GatewayClient) -> str:
    """
    Generate FRP client configuration in TOML format.
    Includes server connection details and all active proxy connections for the client.
    """
    config = f"""
serverAddr = "{client.server.host}"
serverPort = {client.server.bind_port}

[auth]
method = "token"
token = "{client.server.auth_token}"
additionalScopes = ["HeartBeats"]
"""
    # Add all connections for this client
    connections = repos.GatewayConnectionRepo(db).list_by_client_id(client.id)

    for connection in connections:
        config += generate_connection_toml(connection) + "\n"

    return config.strip()


def generate_connection_toml(connection: GatewayConnection) -> str:
    """
    Generate FRP proxy connection configuration in TOML format.
    Returns empty string if connection is inactive.
    """
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
    # Add any additional flags (like encryption settings)
    for flag in connection.flags:
        config += f"{flag}\n"

    return config.strip()