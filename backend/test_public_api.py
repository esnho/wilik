import unittest

from flask import Flask, jsonify
from flask_login import LoginManager

from models import AppSettings, Claim, Gift, User, Wishlist, db
from routes.public import public_bp


class PublicApiTestCase(unittest.TestCase):
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

        self.app.register_blueprint(public_bp)

        with self.app.app_context():
            db.create_all()
            db.session.add(AppSettings(id=1, app_name="Wilik"))
            owner = User(
                username="owner",
                show_in_directory=True,
                theme_color="#0d9488",
            )
            hidden_owner = User(username="hidden", show_in_directory=False)
            db.session.add_all([owner, hidden_owner])
            db.session.commit()
            self.owner_id = owner.id
            natale = Wishlist(owner_id=owner.id, name="Natale")
            compleanno = Wishlist(owner_id=owner.id, name="Compleanno")
            hidden = Wishlist(owner_id=hidden_owner.id, name="Hidden list")
            db.session.add_all([natale, compleanno, hidden])
            db.session.commit()
            self.natale = dict(
                id=natale.id, name=natale.name, share_token=natale.share_token, code=natale.code
            )
            self.compleanno_token = compleanno.share_token
            self.hidden_token = hidden.share_token
            active = Gift(
                owner_id=owner.id, wishlist_id=natale.id, title="Wool socks", received=False
            )
            archived = Gift(
                owner_id=owner.id, wishlist_id=natale.id, title="Old scarf", received=True
            )
            other_list = Gift(
                owner_id=owner.id, wishlist_id=compleanno.id, title="Cake pan", received=False
            )
            db.session.add_all([active, archived, other_list])
            db.session.commit()
            self.active_gift_id = active.id

        self.client = self.app.test_client()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def test_wishlist_page_by_list_token_keeps_today_response_shape(self):
        response = self.client.get(f"/api/public/{self.natale['share_token']}")

        self.assertEqual(response.status_code, 200)
        owner = response.get_json()
        self.assertEqual(owner["list_name"], "Natale")
        for key in [
            "currency",
            "decimal_separator",
            "theme_color",
            "show_background_pattern",
            "guest_sort_by_price_enabled",
            "guest_filter_by_label_enabled",
            "guest_filter_by_brand_enabled",
        ]:
            self.assertIn(key, owner)

    def test_wishlist_page_by_unknown_token_is_not_found(self):
        self.assertEqual(self.client.get("/api/public/no-such-token").status_code, 404)

    def test_public_items_return_only_that_lists_unreceived_gifts(self):
        response = self.client.get(f"/api/public/{self.natale['share_token']}/items")

        self.assertEqual(response.status_code, 200)
        items = response.get_json()
        self.assertEqual([item["title"] for item in items], ["Wool socks"])

    def test_public_directory_lists_every_list_of_opted_in_users(self):
        response = self.client.get("/api/public/directory")

        self.assertEqual(response.status_code, 200)
        body = response.get_json()
        self.assertTrue(body["enabled"])
        entry = next(e for e in body["lists"] if e["share_token"] == self.natale["share_token"])
        self.assertEqual(entry["list_name"], "Natale")
        self.assertEqual(entry["username"], "owner")
        self.assertEqual(entry["theme_color"], "#0d9488")
        # one entry per list, both of the opted-in user's lists are there
        self.assertEqual(len([e for e in body["lists"] if e["username"] == "owner"]), 2)
        self.assertNotIn(self.hidden_token, [e["share_token"] for e in body["lists"]])

    def test_a_visitor_can_claim_an_item_through_a_list_token(self):
        response = self.client.post(
            f"/api/public/{self.natale['share_token']}/items/{self.active_gift_id}/claim",
            json={"name": "Alice"},
        )

        self.assertEqual(response.status_code, 200)
        with self.app.app_context():
            claims = Claim.query.filter_by(gift_id=self.active_gift_id).all()
            self.assertEqual([claim.claimed_by for claim in claims], ["Alice"])

    def test_disabled_directory_hides_every_list(self):
        with self.app.app_context():
            settings = db.session.get(AppSettings, 1)
            settings.public_directory_enabled = False
            db.session.commit()

        response = self.client.get("/api/public/directory")

        self.assertEqual(response.get_json(), {"enabled": False, "lists": []})
