import unittest

from flask import Flask, jsonify
from flask_login import LoginManager

from models import AppSettings, User, Wishlist, db
from routes.admin import admin_bp
from routes.auth import auth_bp


class AccountApiTestCase(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(
            SECRET_KEY="test-secret",
            SQLALCHEMY_DATABASE_URI="sqlite:///:memory:",
            TESTING=True,
        )
        db.init_app(self.app)
        login_manager = LoginManager(self.app)

        @login_manager.user_loader
        def load_user(user_id):
            return db.session.get(User, int(user_id))

        @login_manager.unauthorized_handler
        def unauthorized():
            return jsonify({"error": "Login required"}), 401

        self.app.register_blueprint(auth_bp)
        self.app.register_blueprint(admin_bp)

        with self.app.app_context():
            db.create_all()
            db.session.add(AppSettings(id=1, app_name="Wilik"))
            admin = User(username="Admin", is_admin=True)
            user = User(username="owner")
            db.session.add_all([admin, user])
            db.session.commit()
            self.admin_id = admin.id
            self.user_id = user.id

        self.client = self.app.test_client()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def login_as(self, user_id):
        with self.client.session_transaction() as session:
            session["_user_id"] = str(user_id)
            session["_fresh"] = True

    def test_account_update_no_longer_touches_list_name(self):
        with self.app.app_context():
            user = db.session.get(User, self.user_id)
            user.lists.append(Wishlist(owner_id=user.id, name="Natale"))
            db.session.commit()

        self.login_as(self.user_id)
        response = self.client.put(
            "/api/account", json={"username": "owner", "currency": "€"}
        )

        self.assertEqual(response.status_code, 200)
        with self.app.app_context():
            lists = db.session.get(User, self.user_id).lists
            self.assertEqual([wishlist.name for wishlist in lists], ["Natale"])

    def test_the_account_share_token_endpoint_is_gone(self):
        self.login_as(self.user_id)
        response = self.client.post("/api/account/share-token")

        self.assertEqual(response.status_code, 404)

    def test_creating_a_user_creates_their_default_list(self):
        self.login_as(self.admin_id)
        response = self.client.post("/api/users", json={"username": "Gino"})

        self.assertEqual(response.status_code, 201)
        with self.app.app_context():
            lists = db.session.get(User, response.get_json()["id"]).lists
            self.assertEqual(
                [wishlist.name for wishlist in lists], ["Gino's wishlist"]
            )

    def test_admin_user_update_no_longer_takes_a_list_name(self):
        self.login_as(self.admin_id)
        response = self.client.put(f"/api/users/{self.user_id}", json={"currency": "€"})

        self.assertEqual(response.status_code, 200)
        self.assertNotIn("list_name", response.get_json())
