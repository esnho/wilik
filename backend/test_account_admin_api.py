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

    def test_partial_update_succeeds_when_the_stored_theme_color_is_off_palette(self):
        # a value left over from an older palette (no migration renamed it) must
        # not block unrelated updates: only what the client sends gets validated
        with self.app.app_context():
            user = db.session.get(User, self.user_id)
            user.theme_color = "#e65100"
            db.session.commit()

        self.login_as(self.user_id)
        response = self.client.put(
            "/api/account", json={"guest_sort_by_price_enabled": True}
        )

        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertTrue(body["guest_sort_by_price_enabled"])
        # the legacy value is kept as-is, waiting for the user to pick a swatch
        self.assertEqual(body["theme_color"], "#e65100")

    def test_account_update_sets_the_guest_default_sort(self):
        self.login_as(self.user_id)
        response = self.client.put("/api/account", json={"guest_default_sort": "price"})

        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertEqual(body["guest_default_sort"], "price")

    def test_the_guest_default_sort_defaults_to_the_recommended_order(self):
        self.login_as(self.user_id)
        # no GET endpoint: a partial update echoes back the untouched default
        response = self.client.put("/api/account", json={"currency": "€"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["guest_default_sort"], "recommended")

    def test_an_unknown_guest_default_sort_is_rejected(self):
        self.login_as(self.user_id)
        response = self.client.put("/api/account", json={"guest_default_sort": "rating"})

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"], "Invalid default sort")

    def test_an_explicitly_sent_off_palette_theme_color_is_still_rejected(self):
        self.login_as(self.user_id)
        response = self.client.put(
            "/api/account", json={"theme_color": "#e65100"}
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"], "Invalid theme color")

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

    def test_admin_user_update_sets_the_guest_default_sort(self):
        self.login_as(self.admin_id)
        response = self.client.put(
            f"/api/users/{self.user_id}", json={"guest_default_sort": "price"}
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["guest_default_sort"], "price")

    def test_admin_user_update_rejects_an_unknown_guest_default_sort(self):
        self.login_as(self.admin_id)
        response = self.client.put(
            f"/api/users/{self.user_id}", json={"guest_default_sort": "rating"}
        )

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_json()["error"], "Invalid default sort")
