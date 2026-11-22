import unittest

from flask import Flask, jsonify
from flask_login import LoginManager

from models import AppSettings, Gift, User, Wishlist, db
from routes.lists import lists_bp


class ListsApiTestCase(unittest.TestCase):
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

        self.client = self.app.test_client()

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()

    def login_as(self, user_id):
        with self.client.session_transaction() as session:
            session["_user_id"] = str(user_id)
            session["_fresh"] = True

    def make_list(self, owner_id, name):
        with self.app.app_context():
            wishlist = Wishlist(owner_id=owner_id, name=name)
            db.session.add(wishlist)
            db.session.commit()
            return wishlist.id

    def test_creating_a_list_makes_it_available_to_the_owner(self):
        self.login_as(self.owner_id)
        response = self.client.post("/api/lists", json={"name": "Viaggio in Giappone"})

        self.assertEqual(response.status_code, 201)
        created = response.get_json()
        self.assertEqual(created["name"], "Viaggio in Giappone")
        self.assertIn("code", created)
        self.assertIn("share_token", created)

        with self.app.app_context():
            wishlist = db.session.get(Wishlist, created["id"])
            self.assertEqual(wishlist.owner_id, self.owner_id)

    def test_creating_a_list_with_an_empty_name_is_rejected(self):
        self.login_as(self.owner_id)
        for empty in ["", "   "]:
            response = self.client.post("/api/lists", json={"name": empty})
            self.assertEqual(response.status_code, 400)

        with self.app.app_context():
            self.assertEqual(Wishlist.query.filter_by(owner_id=self.owner_id).count(), 0)

    def test_renaming_a_list_updates_its_name(self):
        wishlist_id = self.make_list(self.owner_id, "Natale")

        self.login_as(self.owner_id)
        response = self.client.put(f"/api/lists/{wishlist_id}", json={"name": "Natale 2026"})

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_json()["name"], "Natale 2026")
        with self.app.app_context():
            self.assertEqual(db.session.get(Wishlist, wishlist_id).name, "Natale 2026")

    def test_renaming_to_an_empty_name_is_rejected(self):
        wishlist_id = self.make_list(self.owner_id, "Natale")

        self.login_as(self.owner_id)
        response = self.client.put(f"/api/lists/{wishlist_id}", json={"name": "  "})

        self.assertEqual(response.status_code, 400)
        with self.app.app_context():
            self.assertEqual(db.session.get(Wishlist, wishlist_id).name, "Natale")

    def test_another_users_list_cannot_be_renamed_or_deleted(self):
        foreign_id = self.make_list(self.other_id, "Not mine")

        self.login_as(self.owner_id)
        rename = self.client.put(f"/api/lists/{foreign_id}", json={"name": "Hijacked"})
        delete = self.client.delete(f"/api/lists/{foreign_id}")

        self.assertEqual(rename.status_code, 403)
        self.assertEqual(delete.status_code, 403)
        with self.app.app_context():
            self.assertEqual(db.session.get(Wishlist, foreign_id).name, "Not mine")

    def test_deleting_a_list_deletes_also_its_gifts(self):
        first_id = self.make_list(self.owner_id, "First")
        wishlist_id = self.make_list(self.owner_id, "Natale")
        with self.app.app_context():
            db.session.add(Gift(owner_id=self.owner_id, wishlist_id=wishlist_id, title="Sock"))
            db.session.commit()

        self.login_as(self.owner_id)
        response = self.client.delete(f"/api/lists/{wishlist_id}")

        self.assertEqual(response.status_code, 204)
        with self.app.app_context():
            self.assertIsNone(db.session.get(Wishlist, wishlist_id))
            self.assertEqual(Gift.query.count(), 0)

    def test_the_last_remaining_list_cannot_be_deleted(self):
        first_id = self.make_list(self.owner_id, "Mine")
        second_id = self.make_list(self.owner_id, "Still mine")

        self.login_as(self.owner_id)
        response = self.client.delete(f"/api/lists/{first_id}")
        self.assertEqual(response.status_code, 204)

        last = self.client.delete(f"/api/lists/{second_id}")
        self.assertEqual(last.status_code, 403)
        with self.app.app_context():
            self.assertIsNotNone(db.session.get(Wishlist, second_id))

    def test_regenerating_a_lists_share_token_gives_a_new_token(self):
        wishlist_id = self.make_list(self.owner_id, "Natale")
        with self.app.app_context():
            old_token = db.session.get(Wishlist, wishlist_id).share_token

        self.login_as(self.owner_id)
        response = self.client.post(f"/api/lists/{wishlist_id}/share-token")

        self.assertEqual(response.status_code, 200)
        new_token = response.get_json()["share_token"]
        self.assertNotEqual(new_token, old_token)
        with self.app.app_context():
            self.assertEqual(db.session.get(Wishlist, wishlist_id).share_token, new_token)

    def test_lists_are_listed_oldest_first_with_their_fields(self):
        natale_id = self.make_list(self.owner_id, "Natale")
        compleanno_id = self.make_list(self.owner_id, "Compleanno")

        self.login_as(self.owner_id)
        response = self.client.get("/api/lists")

        self.assertEqual(response.status_code, 200)
        lists = response.get_json()
        self.assertEqual([wishlist["name"] for wishlist in lists], ["Natale", "Compleanno"])
        self.assertEqual(lists[0]["id"], natale_id)
        self.assertEqual(lists[1]["id"], compleanno_id)
        for wishlist in lists:
            self.assertEqual(
                set(wishlist.keys()), {"id", "name", "code", "share_token", "gift_count"}
            )

    def test_lists_only_show_the_current_users_lists(self):
        self.make_list(self.owner_id, "Mine")
        foreign_id = self.make_list(self.other_id, "Not mine")

        self.login_as(self.owner_id)
        response = self.client.get("/api/lists")

        lists = response.get_json()
        self.assertEqual([wishlist["name"] for wishlist in lists], ["Mine"])
        self.assertNotIn(foreign_id, [wishlist["id"] for wishlist in lists])
