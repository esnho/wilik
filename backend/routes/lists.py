from flask import Blueprint, jsonify, request
from flask_login import current_user, login_required

from models import Wishlist, db, generate_share_token

lists_bp = Blueprint("lists", __name__, url_prefix="/api")


def get_owned_list_or_response(list_id):
    """The user's list with this id, or the error response to return instead:
    404 when it doesn't exist, 403 when it belongs to another user."""
    wishlist = db.session.get(Wishlist, list_id)
    if wishlist is None:
        return None, (jsonify({"error": "List not found"}), 404)
    if wishlist.owner_id != current_user.id:
        return None, (jsonify({"error": "Not your list"}), 403)
    return wishlist, None


@lists_bp.route("/lists/<int:list_id>", methods=["PUT"])
@login_required
def rename_list(list_id):
    wishlist, error = get_owned_list_or_response(list_id)
    if error:
        return error
    data = request.get_json()
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "List name can't be empty"}), 400
    wishlist.name = name
    db.session.commit()
    return jsonify(wishlist.to_dict())


@lists_bp.route("/lists/<int:list_id>", methods=["DELETE"])
@login_required
def delete_list(list_id):
    wishlist, error = get_owned_list_or_response(list_id)
    if error:
        return error
    if len(current_user.lists) <= 1:
        return jsonify({"error": "You can't delete your last list"}), 403
    db.session.delete(wishlist)
    db.session.commit()
    return "", 204


@lists_bp.route("/lists/<int:list_id>/share-token", methods=["POST"])
@login_required
def regenerate_list_share_token(list_id):
    wishlist, error = get_owned_list_or_response(list_id)
    if error:
        return error
    wishlist.share_token = generate_share_token()
    db.session.commit()
    return jsonify(wishlist.to_dict())


@lists_bp.route("/lists")
@login_required
def get_lists():
    return jsonify([wishlist.to_dict() for wishlist in current_user.lists])


@lists_bp.route("/lists", methods=["POST"])
@login_required
def create_list():
    data = request.get_json()
    name = (data.get("name") or "").strip()
    if not name:
        return jsonify({"error": "List name can't be empty"}), 400
    wishlist = Wishlist(owner_id=current_user.id, name=name)
    db.session.add(wishlist)
    db.session.commit()
    return jsonify(wishlist.to_dict()), 201
