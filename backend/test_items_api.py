import unittest

from flask import Flask, jsonify
from flask_login import LoginManager

from models import AppSettings, Gift, User, Wishlist, db
from routes.items import items_bp
from routes.lists import lists_bp


class ItemsApiTestCase(unittest.TestCase):
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

        self.app.register_blueprint(items_bp)
        self.app.register_blueprint(lists_bp)

        with self.app.app_context():
            db.create_all()
            db.session.add(AppSettings(id=1, app_name="Wilik"))
            owner = User(username="owner")
            other = User(username="other")
            db.session.add_all([owner, other])
            db.session.commit()
            self.owner_id = owner.id
            self.other_id = other.id
            natale = Wishlist(owner_id=owner.id, name="Natale")
            compleanno = Wishlist(owner_id=owner.id, name="Compleanno")
            db.session.add_all([natale, compleanno])
            db.session.commit()
            self.natale_id = natale.id
            self.compleanno_id = compleanno.id
            gift = Gift(
                owner_id=owner.id, wishlist_id=natale.id, title="Wool socks", received=False
            )
            db.session.add(gift)
            db.session.commit()
            self.gift_id = gift.id

        self.client = self.app.test_client()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def login_as(self, user_id):
        with self.client.session_transaction() as session:
            session["_user_id"] = str(user_id)
            session["_fresh"] = True

    def test_items_can_be_filtered_by_list(self):
        self.login_as(self.owner_id)
        response = self.client.get(f"/api/items?list_id={self.natale_id}")

        self.assertEqual(response.status_code, 200)
        items = response.get_json()
        self.assertEqual([item["title"] for item in items], ["Wool socks"])

    def test_items_without_list_parameter_return_all_owned_gifts(self):
        with self.app.app_context():
            db.session.add(
                Gift(owner_id=self.owner_id, wishlist_id=self.compleanno_id, title="Cake pan")
            )
            db.session.add(
                Gift(owner_id=self.owner_id, wishlist_id=self.natale_id, title="Archive")
            )
            db.session.commit()

        self.login_as(self.owner_id)
        response = self.client.get("/api/items")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(
            sorted(item["title"] for item in response.get_json()),
            ["Archive", "Cake pan", "Wool socks"],
        )

    def test_filtering_by_another_users_list_is_rejected(self):
        with self.app.app_context():
            foreign = Wishlist(owner_id=self.other_id, name="Not mine")
            db.session.add(foreign)
            db.session.commit()
            foreign_id = foreign.id

        self.login_as(self.owner_id)
        response = self.client.get(f"/api/items?list_id={foreign_id}")

        self.assertEqual(response.status_code, 403)

    def test_creating_an_item_into_a_specific_list(self):
        self.login_as(self.owner_id)
        response = self.client.post(
            "/api/items", json={"title": "Hot sauce", "list_id": self.compleanno_id}
        )

        self.assertEqual(response.status_code, 201)
        with self.app.app_context():
            gift = db.session.get(Gift, response.get_json()["id"])
            self.assertEqual(gift.wishlist_id, self.compleanno_id)
            self.assertEqual(gift.owner_id, self.owner_id)

    def test_creating_an_item_without_list_id_uses_the_first_list(self):
        self.login_as(self.owner_id)
        response = self.client.post("/api/items", json={"title": "Hot sauce"})

        self.assertEqual(response.status_code, 201)
        with self.app.app_context():
            gift = db.session.get(Gift, response.get_json()["id"])
            self.assertEqual(gift.wishlist_id, self.natale_id)

    def test_creating_an_item_into_another_users_list_is_rejected(self):
        with self.app.app_context():
            foreign = Wishlist(owner_id=self.other_id, name="Not mine")
            db.session.add(foreign)
            db.session.commit()
            foreign_id = foreign.id

        self.login_as(self.owner_id)
        response = self.client.post(
            "/api/items", json={"title": "Hot sauce", "list_id": foreign_id}
        )

        self.assertEqual(response.status_code, 403)
