import unittest

from flask import Flask, jsonify
from flask_login import LoginManager

from models import AppSettings, User, db
from routes.admin import admin_bp


class DirectoryButtonTestCase(unittest.TestCase):
    """public_directory_button_enabled hides the "All wishlists" button from guests viewing
    a public wishlist (frontend-side); here we cover the setting itself through the API."""

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

        self.app.register_blueprint(admin_bp)

        with self.app.app_context():
            db.create_all()
            db.session.add(AppSettings(id=1, app_name="Wilik"))
            admin = User(username="admin", is_admin=True)
            member = User(username="member", is_admin=False)
            db.session.add_all([admin, member])
            db.session.commit()
            self.admin_id = admin.id
            self.member_id = member.id

        self.client = self.app.test_client()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def login_as(self, user_id):
        with self.client.session_transaction() as session:
            session["_user_id"] = str(user_id)
            session["_fresh"] = True

    def test_defaults_to_showing_the_button(self):
        data = self.client.get("/api/settings").get_json()
        self.assertTrue(data["public_directory_button_enabled"])

    def test_admin_can_hide_the_button(self):
        self.login_as(self.admin_id)
        response = self.client.put(
            "/api/settings",
            json={"public_directory_button_enabled": False},
        )
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.get_json()["public_directory_button_enabled"])

    def test_non_admin_cannot_update_the_button(self):
        self.login_as(self.member_id)
        response = self.client.put(
            "/api/settings",
            json={"public_directory_button_enabled": False},
        )
        self.assertEqual(response.status_code, 403)
        self.assertTrue(self.client.get("/api/settings").get_json()["public_directory_button_enabled"])


if __name__ == "__main__":
    unittest.main()
