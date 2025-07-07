from datetime import timedelta
import json
import random
import threading
import time
import uuid
import waitress
from flask import Flask, abort, flash, jsonify, redirect, render_template, request, session, url_for
from core.autofrp import AutoFRPManager, FRPSWebserver, FRPServer, FRPClient, FRPConnection
from core.nginx import NginxConfigManager, ProxyTarget
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

class ProxyManager:
    def __init__(self, nginx_manager: NginxConfigManager, frp_manager: AutoFRPManager, application_root, USERNAME, PASSWORD, allowed_api_keys = []):
        self.nginx_manager = nginx_manager
        self.frp_manager = frp_manager
        self.USERNAME = USERNAME
        self.PASSWORD = PASSWORD
        self.allowed_api_keys = allowed_api_keys

        self.app = Flask("ProxyManager", template_folder='core/templates')
        self.app.config.update(
            APPLICATION_ROOT=application_root,
            # SESSION_COOKIE_SECURE=True,       # only sent over HTTPS
            # SESSION_COOKIE_HTTPONLY=True,     # JS can’t read
            # SESSION_COOKIE_SAMESITE="Strict", # no cross-site requests
            # PERMANENT_SESSION_LIFETIME=timedelta(minutes=30),
        )
        self.app.secret_key = uuid.uuid4().hex

        self.limiter = Limiter(
            key_func=lambda: "dashboard-owner",
            storage_uri="memory://",
            default_limits=["10 per second", "60 per minute"],
        )
        self.limiter.init_app(self.app)

        self.app.errorhandler(404)(self.standard_error)
        self.app.errorhandler(405)(self.standard_error)

        self.app.add_url_rule('/', 'index', self.index)
        self.app.add_url_rule('/login', 'login', self.login, methods=['GET', 'POST'])
        self.app.add_url_rule('/logout', 'logout', self.logout)
        # self.app.add_url_rule('/keys', 'keys', self.get_keys, methods=['GET'])
        self.app.add_url_rule('/logs', 'logs', self.get_logs, methods=['GET'])
        self.app.add_url_rule('/add_route', 'add_route', self.add_route, methods=['GET', 'POST'])
        self.app.add_url_rule('/edit_route', 'edit_route', self.edit_route, methods=['GET', 'POST'])
        self.app.add_url_rule('/toggle_route', 'toggle_route', self.toggle_route, methods=['POST'])
        self.app.add_url_rule('/delete_route', 'delete_route', self.delete_route, methods=['POST'])
        self.app.add_url_rule('/add_redirect', 'add_redirect', self.add_redirect, methods=['GET', 'POST'])
        self.app.add_url_rule('/reload_nginx', 'reload_nginx', self.reload_nginx, methods=['POST'])

        self.app.add_url_rule('/add_gateway_server', 'add_gateway_server', self.add_gateway_server, methods=['GET', 'POST'])
        self.app.add_url_rule('/add_gateway_client', 'add_gateway_client', self.add_gateway_client, methods=['GET', 'POST'])
        self.app.add_url_rule('/add_gateway_connection', 'add_gateway_connection', self.add_gateway_connection, methods=['GET', 'POST'])
        self.app.add_url_rule('/edit_gateway_server', 'edit_gateway_server', self.edit_gateway_server, methods=['GET', 'POST'])
        self.app.add_url_rule('/edit_gateway_client', 'edit_gateway_client', self.edit_gateway_client, methods=['GET', 'POST'])
        self.app.add_url_rule('/edit_gateway_connection', 'edit_gateway_connection', self.edit_gateway_connection, methods=['GET', 'POST'])
        self.app.add_url_rule('/delete_gateway_server', 'delete_gateway_server', self.delete_gateway_server, methods=['POST'])
        self.app.add_url_rule('/delete_gateway_client', 'delete_gateway_client', self.delete_gateway_client, methods=['POST'])
        self.app.add_url_rule('/delete_gateway_connection', 'delete_gateway_connection', self.delete_gateway_connection, methods=['POST'])
        self.app.add_url_rule('/toggle_gateway_connection', 'toggle_gateway_connection', self.toggle_gateway_connection, methods=['POST'])

        self.app.add_url_rule('/api/gateway/server/<server_id>', 'gateway_server_config', self.get_gateway_server_config, methods=['GET'])
        self.app.add_url_rule('/api/gateway/client/<client_id>', 'gateway_client_config', self.get_gateway_client_config, methods=['GET'])

    def run(self):
        print("Running server")
        waitress.serve(self.app, host='127.0.0.1', port=8080)

    def standard_error(self, error):
        time.sleep(random.uniform(4, 6))

        # return render_template("404.html"), 404
        return render_template("status_code.jinja", status_code=404), 404

    def get_logs(self):
        if not session.get('logged_in'):
            return abort(404)

        key_set = request.args.get('key') != None
        logType = request.args.get('type')

        if logType == "access":
            logFile = "/var/log/nginx/access.log"
        elif logType == "stream":
            logFile = "/var/log/nginx/stream.log"
        else:
            return render_template("select_logs.jinja", application_root=self.app.config['APPLICATION_ROOT'])

        with open(logFile, "r") as f:
            lines = f.readlines()

        if key_set:
            return "\n".join(lines)

        lines = lines[::-1]

        return render_template("logs.jinja", application_root=self.app.config['APPLICATION_ROOT'], logType=logType.upper(), lines=lines)

    # def get_keys(self):
    #     key = request.args.get('key')
    #     if key in self.allowed_api_keys:
    #         return jsonify({"u": self.USERNAME, "p": self.PASSWORD})

    #     return abort(404)
    
    def login(self):
        if session.get('logged_in'):
            return redirect(self.app.config['APPLICATION_ROOT'] + url_for('index'))

        if request.method == 'POST':
            username = request.form['username']
            password = request.form['password']
            if username == self.USERNAME and password == self.PASSWORD:
                session['logged_in'] = True
                return redirect(self.app.config['APPLICATION_ROOT'] + url_for('index'))
            else:
                time.sleep(5)
                flash('Invalid username or password', 'error')

        return render_template("login.html")


    def logout(self):
        session.pop('logged_in', None)
        flash('Logged out successfully', 'success')
        return redirect(self.app.config['APPLICATION_ROOT'] + url_for('login'))

    def index(self):
        if not session.get('logged_in'):
            return redirect(self.app.config['APPLICATION_ROOT'] + url_for('login'))

        return render_template("index.jinja", 
                               proxy_map=self.nginx_manager.proxy_map, 
                               gateway_server_list=self.frp_manager.get_server_list(), 
                               gateway_client_list=self.frp_manager.get_client_list(), 
                               gateway_connection_list=self.frp_manager.get_connection_list(), 
                               domain=self.nginx_manager.domain, 
                               application_root=self.app.config['APPLICATION_ROOT'])





    def add_route(self):
        if not session.get('logged_in'):
            return abort(404)

        if request.method == 'POST':
            server_type = request.form['server_type']
            subdomain = request.form['subdomain']
            path = request.form['path']
            targets = request.form['targets']
            srv_record = request.form.get('srv_record', '').strip()
            if srv_record == '':
                srv_record = None

            newTargets = []
            for target in json.loads(targets):
                newTargets.append(ProxyTarget(target['server'], target['weight'], target['max_fails'], target['fail_timeout'], target['backup'], target['active']))

            if server_type == "http":
                protocol = request.form['protocol']
                backend_path = request.form['backend_path']
                self.nginx_manager.add_http_proxy(subdomain.strip(), path.strip(), protocol, backend_path, newTargets)
            elif server_type == "stream":
                self.nginx_manager.add_stream_proxy(subdomain.strip(), int(path.strip()), newTargets, srv_record=srv_record)

            flash('Route added successfully', 'success')
            return redirect(self.app.config['APPLICATION_ROOT'] + url_for('index'))

        return render_template("add_route.jinja", application_root=self.app.config['APPLICATION_ROOT'])



    def edit_route(self):
        if not session.get('logged_in'):
            return abort(404)

        if request.method == 'POST':
            server_type = request.form['server_type']
            original_subdomain = request.form['original_subdomain']
            subdomain = request.form['subdomain']
            path = request.form['path']
            protocol = request.form['protocol']
            backend_path = request.form['backend_path']
            targets = request.form['targets']
            srv_record = request.form.get('srv_record', '').strip()
            if srv_record == '':
                srv_record = None

            newTargets = []
            for target in json.loads(targets):
                newTargets.append(ProxyTarget(target['server'], target['weight'], target['max_fails'], target['fail_timeout'], target['backup'], target['active']))

            if server_type == "http":
                self.nginx_manager.update_http_proxy_targets(original_subdomain.strip(), path.strip(), protocol, backend_path, newTargets, new_subdomain=subdomain)
            elif server_type == "stream":
                self.nginx_manager.update_stream_proxy_targets(original_subdomain.strip(), int(path.strip()), newTargets, srv_record=srv_record, new_subdomain=subdomain)

            flash('Route updated successfully', 'success')
            return redirect(self.app.config['APPLICATION_ROOT'] + url_for('index'))

        server_type = request.args.get('server_type')
        subdomain = request.args.get('subdomain')
        path = request.args.get('path')

        if subdomain not in self.nginx_manager.proxy_map[server_type]:
            return abort(404)

        if path not in self.nginx_manager.proxy_map[server_type][subdomain]:
            return abort(404)

        data = self.nginx_manager.proxy_map[server_type][subdomain][path]
        protocol = data.get("protocol", "http://")
        backend_path = data.get("path", "")
        srv_record = data.get("srv_record", "")

        return render_template("edit_route.jinja", application_root=self.app.config['APPLICATION_ROOT'], proxy_map=self.nginx_manager.proxy_map, server_type=server_type, subdomain=subdomain, path=path, protocol=protocol, backend_path=backend_path, srv_record=srv_record)



    def toggle_route(self):
        if not session.get('logged_in'):
            return abort(404)

        server_type = request.form['server_type']
        subdomain = request.form['subdomain']
        path = request.form['path']
        if self.nginx_manager.proxy_map[server_type][subdomain][path]["active"]:
            self.nginx_manager.set_active(server_type, subdomain, path, False)
        else:

            self.nginx_manager.set_active(server_type, subdomain, path, True)
        return redirect(self.app.config['APPLICATION_ROOT'] + url_for('index'))

    def delete_route(self):
        if not session.get('logged_in'):
            return abort(404)

        server_type = request.form['server_type']
        subdomain = request.form['subdomain']
        path = request.form['path']
        if server_type == "http":
            self.nginx_manager.remove_http_proxy(subdomain, path)
        elif server_type == "stream":
            self.nginx_manager.remove_stream_proxy(subdomain, path)

        flash('Route deleted successfully', 'success')
        return redirect(self.app.config['APPLICATION_ROOT'] + url_for('index'))


    def add_redirect(self):
        if not session.get('logged_in'):
            return abort(404)

        if request.method == 'POST':
            subdomain = request.form['subdomain']
            path = request.form['path']
            route = request.form['route']

            self.nginx_manager.add_redirect(subdomain, path, route)

            flash('Redirect added successfully', 'success')
            return redirect(self.app.config['APPLICATION_ROOT'] + url_for('index'))

        return render_template("add_redirect.jinja", application_root=self.app.config['APPLICATION_ROOT'])




    def reload_nginx(self):
        if not session.get('logged_in'):
            return abort(404)

        def timer():
            time.sleep(2)
            self.nginx_manager.reload_nginx()

        threading.Thread(target=timer).start()

        return render_template('reload.jinja', application_root=self.app.config['APPLICATION_ROOT'])









    def add_gateway_server(self):
        if not session.get('logged_in'):
            return abort(404)

        if request.method == 'POST':
            form_dict = request.form.to_dict()
            webserver = None
            if form_dict.get("webserver_addr", '').strip() != '':
                webserver = FRPSWebserver(
                    host=form_dict['webserver_addr'],
                    port=int(form_dict['webserver_port']),
                    user=form_dict.get('webserver_user', '').strip(),
                    password=form_dict.get('webserver_password', '').strip()
                )

            server = FRPServer(
                id=form_dict['id'],
                host=form_dict['host'],
                bind_port=int(form_dict['bind_port']),
                auth_token=form_dict['auth_token'],
                webserver=webserver
            )

            try:
                self.frp_manager.add_server(server)

                flash('Gateway server added successfully', 'success')
            except Exception as e:
                flash(f'Error adding gateway server: {str(e)}', 'error')
                
            return redirect(self.app.config['APPLICATION_ROOT'] + url_for('index'))

        return render_template("add_gateway_server.jinja", application_root=self.app.config['APPLICATION_ROOT'])
    
    def edit_gateway_server(self):
        if not session.get('logged_in'):
            return abort(404)

        server_id = request.args.get('server_id')
        server = self.frp_manager.get_server_by_id(server_id)
        if not server:
            return abort(404)

        if request.method == 'POST':
            form_dict = request.form.to_dict()
            webserver = None
            if form_dict.get("webserver_addr", '').strip() != '':
                webserver = FRPSWebserver(
                    addr=form_dict['webserver_addr'],
                    port=int(form_dict['webserver_port']),
                    user=form_dict.get('webserver_user', '').strip(),
                    password=form_dict.get('webserver_password', '').strip()
                )

            server.host = form_dict['host']
            server.bind_port = int(form_dict['bind_port'])
            server.auth_token = form_dict['auth_token']
            server.webserver = webserver

            try:
                self.frp_manager.update_server(server)
                flash('Gateway server updated successfully', 'success')
            except Exception as e:
                flash(f'Error updating gateway server: {str(e)}', 'error')

            return redirect(self.app.config['APPLICATION_ROOT'] + url_for('index'))

        return render_template("edit_gateway_server.jinja", application_root=self.app.config['APPLICATION_ROOT'], server=server)
    
    def delete_gateway_server(self):
        if not session.get('logged_in'):
            return abort(404)

        server_id = request.form['server_id']
        try:
            self.frp_manager.remove_server(server_id)
            flash('Gateway server deleted successfully', 'success')
        except Exception as e:
            flash(f'Error deleting gateway server: {str(e)}', 'error')

        return redirect(self.app.config['APPLICATION_ROOT'] + url_for('index'))
    
    def add_gateway_client(self):
        if not session.get('logged_in'):
            return abort(404)

        if request.method == 'POST':
            client = FRPClient(
                id=request.form['client_id'],
                server=self.frp_manager.get_server_by_id(request.form['server_id'])
            )

            try:
                self.frp_manager.add_client(client)
                flash('Gateway client added successfully', 'success')
            except Exception as e:
                flash(f'Error adding gateway client: {str(e)}', 'error')

            return redirect(self.app.config['APPLICATION_ROOT'] + url_for('index'))

        return render_template("add_gateway_client.jinja", application_root=self.app.config['APPLICATION_ROOT'], gateway_server_list=self.frp_manager.get_server_list())

    def edit_gateway_client(self):
        if not session.get('logged_in'):
            return abort(404)

        client_id = request.args.get('client_id')
        client = self.frp_manager.get_client_by_id(client_id)
        if not client:
            return abort(404)

        if request.method == 'POST':
            client.server = self.frp_manager.get_server_by_id(request.form['server_id'])
            client.id = request.form['client_id']

            try:
                self.frp_manager.update_client(client)
                flash('Gateway client updated successfully', 'success')
            except Exception as e:
                flash(f'Error updating gateway client: {str(e)}', 'error')

            return redirect(self.app.config['APPLICATION_ROOT'] + url_for('index'))

        return render_template("edit_gateway_client.jinja", application_root=self.app.config['APPLICATION_ROOT'], client=client, gateway_server_list=self.frp_manager.get_server_list())

    def delete_gateway_client(self):
        if not session.get('logged_in'):
            return abort(404)

        client_id = request.form['client_id']
        try:
            self.frp_manager.remove_client(client_id)
            flash('Gateway client deleted successfully', 'success')
        except Exception as e:
            flash(f'Error deleting gateway client: {str(e)}', 'error')

        return redirect(self.app.config['APPLICATION_ROOT'] + url_for('index'))

    def add_gateway_connection(self):
        if not session.get('logged_in'):
            return abort(404)

        if request.method == 'POST':
            client_id = request.form['client_id']
            name = request.form['name']
            type_ = request.form['type']
            local_ip = request.form['local_ip']
            local_port = int(request.form['local_port'])
            remote_port = int(request.form['remote_port'])
            flags = request.form.getlist('flags')

            connection = FRPConnection(
                name=name,
                type=type_,
                localIP=local_ip,
                localPort=local_port,
                remotePort=remote_port,
                flags=flags
            )

            try:
                self.frp_manager.add_connection_to_client(client_id, connection)
                flash('Gateway connection added successfully', 'success')
            except Exception as e:
                flash(f'Error adding gateway connection: {str(e)}', 'error')

            return redirect(self.app.config['APPLICATION_ROOT'] + url_for('index'))

        return render_template("add_gateway_connection.jinja", application_root=self.app.config['APPLICATION_ROOT'], gateway_client_list=self.frp_manager.get_client_list(), all_flags=GATEWAY_FLAGS.get_all_flags())
    
    def edit_gateway_connection(self):
        if not session.get('logged_in'):
            return abort(404)

        client_id = request.args.get('client_id')
        connection_name = request.args.get('connection_name')
        connection = self.frp_manager.get_connection_by_name(client_id, connection_name)
        if not connection:
            return abort(404)

        if request.method == 'POST':
            connection.name = request.form['name']
            connection.type = request.form['type']
            connection.localIP = request.form['local_ip']
            connection.localPort = int(request.form['local_port'])
            connection.remotePort = int(request.form['remote_port'])
            connection.flags = request.form.getlist('flags')

            try:
                self.frp_manager.update_connection(client_id, connection)
                flash('Gateway connection updated successfully', 'success')
            except Exception as e:
                flash(f'Error updating gateway connection: {str(e)}', 'error')

            return redirect(self.app.config['APPLICATION_ROOT'] + url_for('index'))

        return render_template("edit_gateway_connection.jinja", application_root=self.app.config['APPLICATION_ROOT'], client_id=client_id, connection=connection, all_flags=GATEWAY_FLAGS.get_all_flags())

    def delete_gateway_connection(self):
        if not session.get('logged_in'):
            return abort(404)

        client_id = request.form['client_id']
        connection_name = request.form['connection_name']

        try:
            self.frp_manager.remove_connection_from_client(client_id, connection_name)
            flash('Gateway connection deleted successfully', 'success')
        except Exception as e:
            flash(f'Error deleting gateway connection: {str(e)}', 'error')

        return redirect(self.app.config['APPLICATION_ROOT'] + url_for('index'))
    
    def toggle_gateway_connection(self):
        if not session.get('logged_in'):
            return abort(404)

        client_id = request.form['client_id']
        connection_name = request.form['connection_name']

        try:
            self.frp_manager.toggle_connection(client_id, connection_name)
            flash('Gateway connection toggled successfully', 'success')
        except Exception as e:
            flash(f'Error toggling gateway connection: {str(e)}', 'error')

        return redirect(self.app.config['APPLICATION_ROOT'] + url_for('index'))
    
    def get_gateway_server_config(self, server_id):
        token = request.headers.get("X-Gateway-Token")
        if not token:
            return abort(404)

        server = self.frp_manager.get_server_by_id(server_id)
        if not server:
            return abort(404)
        
        if not token == server.auth_token:
            return abort(404)
        
        server.was_requested()

        return server.generate_config_toml()

    def get_gateway_client_config(self, client_id):
        token = request.headers.get("X-Gateway-Token")
        if not token:
            return abort(404)

        client = self.frp_manager.get_client_by_id(client_id)
        if not client:
            return abort(404)

        if not token == client.server.auth_token:
            return abort(404)

        client.was_requested()

        return client.generate_config_toml()
    
class GATEWAY_FLAGS:
    all_flags = ['transport.useEncryption = true',]

    @classmethod
    def get_all_flags(cls):
        return cls.all_flags

    @classmethod
    def is_valid_flag(cls, flag):
        return flag in cls.all_flags