from abc import ABC, abstractmethod

import flask


class AuthInterface(ABC):
    @abstractmethod
    def get_user(self, flask_request) -> any:
        pass

    @abstractmethod
    def is_logged_in(self, user: any) -> bool:
        pass

    @abstractmethod
    def override_config_for_user(self, user: any, config: dict) -> dict:
        pass

    @abstractmethod
    def login_form(self) -> str:
        pass

    @abstractmethod
    def login_handler(self, flask_request) -> str:
        pass

    @abstractmethod
    def callback_handler(self, flask_request) -> str:
        pass

    @abstractmethod
    def logout_handler(self, flask_request) -> str:
        pass

class NoAuth(AuthInterface):
    def get_user(self, flask_request) -> any:
        return {}

    def is_logged_in(self, user: any) -> bool:
        return True

    def override_config_for_user(self, user: any, config: dict) -> dict:
        return config

    def login_form(self) -> str:
        return ''

    def login_handler(self, flask_request) -> str:
        return 'No login required'

    def callback_handler(self, flask_request) -> str:
        return 'No login required'

    def logout_handler(self, flask_request) -> str:
        return 'No login required'


from flask import jsonify, redirect, session

class BasicAuth(AuthInterface):
    def __init__(self):
        self.users = {"test": "1234"}  # Example username-password dictionary

    def get_user(self, flask_request) -> any:
        return flask_request.json.get("username")

    def is_logged_in(self, user: any) -> bool:
        return user in self.users

    def override_config_for_user(self, user: any, config: dict) -> dict:
        return config

    def login_form(self) -> str:
        return '<form action="/auth/login" method="post"><input name="username"><input name="password" type="password"><button type="submit">Login</button></form>'

    def login_handler(self, flask_request):
        data = flask_request.json or {}
        username = data.get("username")
        password = data.get("password")

        if not username or not password:
            return jsonify({"error": "Username and password are required"}), 400

        if username in self.users and self.users[username] == password:
            session['username'] = username
            return jsonify({
                "message": f"lol {username}! Login successful.",
                "redirect_url": "/vite/"  # Adjust the redirect URL as needed
            }), 200

        return jsonify({"error": "Invalid username or password"}), 401

    def callback_handler(self, flask_request) -> str:
        # Implement your callback logic here
        return jsonify({"message": "Callback handler invoked"}), 200

    def logout_handler(self, flask_request) -> str:
        session.pop('username', None)
        return jsonify({"message": "Logged out successfully."}), 200