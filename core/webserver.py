import json
import random
import threading
import time
import uuid
import waitress
from flask import Flask, abort, flash, jsonify, redirect, render_template, request, session, url_for
from core.nginx import NginxConfigManager, ProxyTarget


class ProxyManager:
    def __init__(self, nginx_manager: NginxConfigManager, application_root, USERNAME, PASSWORD, allowed_api_keys = []):
        self.nginx_manager = nginx_manager
        self.USERNAME = USERNAME
        self.PASSWORD = PASSWORD
        self.allowed_api_keys = allowed_api_keys

        self.app = Flask("ProxyManager", template_folder='core/templates')
        self.app.config['APPLICATION_ROOT'] = application_root
        self.app.secret_key = uuid.uuid4().hex

        self.app.errorhandler(404)(self.standard_error)
        self.app.errorhandler(405)(self.standard_error)

        self.app.add_url_rule('/', 'index', self.index)
        self.app.add_url_rule('/login', 'login', self.login, methods=['GET', 'POST'])
        self.app.add_url_rule('/logout', 'logout', self.logout)
        self.app.add_url_rule('/keys', 'keys', self.get_keys, methods=['GET'])
        self.app.add_url_rule('/logs', 'logs', self.get_logs, methods=['GET'])
        self.app.add_url_rule('/add_route', 'add_route', self.add_route, methods=['GET', 'POST'])
        self.app.add_url_rule('/edit_route', 'edit_route', self.edit_route, methods=['GET', 'POST'])
        self.app.add_url_rule('/toggle_route', 'toggle_route', self.toggle_route, methods=['POST'])
        self.app.add_url_rule('/delete_route', 'delete_route', self.delete_route, methods=['POST'])
        self.app.add_url_rule('/add_redirect', 'add_redirect', self.add_redirect, methods=['GET', 'POST'])
        self.app.add_url_rule('/reload_nginx', 'reload_nginx', self.reload_nginx, methods=['POST'])

    def run(self):
        print("Running server")
        waitress.serve(self.app, host='127.0.0.1', port=8080)

    def standard_error(self, error):
        time.sleep(random.uniform(4, 6))

        # return render_template("404.html"), 404
        return render_template("status_code.jinja", status_code=404), 404

    def get_logs(self):
        if not (session.get('logged_in') or (request.args.get('key') and request.args.get('key') == "***REMOVED***")):
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

    def get_keys(self):
        key = request.args.get('key')
        if key in self.allowed_api_keys:
            return jsonify({"u": self.USERNAME, "p": self.PASSWORD})

        return abort(404)

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

        return render_template("index.jinja", proxy_map=self.nginx_manager.proxy_map, domain=self.nginx_manager.domain, application_root=self.app.config['APPLICATION_ROOT'])





    def add_route(self):
        if not session.get('logged_in'):
            return abort(404)

        print(request.form)

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
                self.nginx_manager.update_http_proxy_targets(subdomain.strip(), path.strip(), protocol, backend_path, newTargets)
            elif server_type == "stream":
                self.nginx_manager.update_stream_proxy_targets(subdomain.strip(), int(path.strip()), newTargets, srv_record=srv_record)

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
