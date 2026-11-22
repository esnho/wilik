import secrets

from flask import Blueprint, jsonify, request

from models import AppSettings, Claim, Gift, User, Wishlist, db

public_bp = Blueprint("public", __name__, url_prefix="/api")


def get_public_list(token):
    """The list whose public link this is, or None: since the share token lives on the
    wishlist, every public lookup starts here instead of on the user."""
    return Wishlist.query.filter_by(share_token=token).first()


@public_bp.route("/public/directory")
def public_directory():
    # lets visitors find a wishlist without needing its share link -- admin-toggleable
    # since it means every list becomes discoverable to anyone who reaches this page
    settings = AppSettings.query.get(1)
    if not settings.public_directory_enabled:
        return jsonify({"enabled": False, "lists": []})
    wishlists = (
        Wishlist.query.join(User).filter(User.show_in_directory == True).order_by(Wishlist.name).all()  # noqa: E712
    )
    lists = [
        {
            "list_name": wishlist.name,
            "username": wishlist.owner.username,
            "share_token": wishlist.share_token,
            "theme_color": wishlist.owner.theme_color,
        }
        for wishlist in wishlists
    ]
    return jsonify({"enabled": True, "lists": lists})


@public_bp.route("/public/<token>")
def public_wishlist(token):
    wishlist = get_public_list(token)
    if wishlist is None:
        return jsonify({"error": "Not found"}), 404
    owner = wishlist.owner.public_dict()
    owner["list_name"] = wishlist.name
    return jsonify(owner)


@public_bp.route("/public/<token>/items")
def public_items(token):
    wishlist = get_public_list(token)
    if wishlist is None:
        return jsonify({"error": "Not found"}), 404
    gifts = Gift.query.filter_by(wishlist_id=wishlist.id, received=False).all()
    return jsonify([gift.to_dict(include_claim_status=True) for gift in gifts])


@public_bp.route("/public/<token>/items/<int:item_id>/claim", methods=["POST"])
def claim_item(token, item_id):
    wishlist = get_public_list(token)
    if wishlist is None:
        return jsonify({"error": "Not found"}), 404
    gift = db.get_or_404(Gift, item_id)
    if gift.wishlist_id != wishlist.id:
        return jsonify({"error": "Not found"}), 404
    data = request.get_json()
    name = data.get("name", "").strip()
    if not name:
        return jsonify({"error": "Enter your name"}), 400

    # always creates a new, independent claim -- never tries to recognize an existing
    # name and reuse it, so a typo while trying to *release* a claim (see verify_claim)
    # can never silently create an unwanted extra claim instead
    claimed_count = len(gift.claims)
    if gift.quantity is not None and claimed_count >= gift.quantity:
        return jsonify({"error": "Already claimed"}), 409

    claim = Claim(gift_id=gift.id, claimed_by=name, claim_token=secrets.token_urlsafe(24))
    db.session.add(claim)
    db.session.commit()
    result = gift.to_dict(include_claim_status=True)
    result["claim_token"] = claim.claim_token  # only ever returned here, to the claimer themselves
    return jsonify(result)


@public_bp.route("/public/<token>/items/<int:item_id>/verify-claim", methods=["POST"])
def verify_claim(token, item_id):
    """Confirms a name matches an existing claim without releasing it -- lets a
    visitor on a different device 'reclaim' their own item before deciding to
    actually unclaim it, instead of that happening in the same step."""
    wishlist = get_public_list(token)
    if wishlist is None:
        return jsonify({"error": "Not found"}), 404
    gift = db.get_or_404(Gift, item_id)
    if gift.wishlist_id != wishlist.id:
        return jsonify({"error": "Not found"}), 404
    data = request.get_json()
    name = data.get("name", "").strip()
    claim = Claim.query.filter(
        Claim.gift_id == gift.id, db.func.lower(Claim.claimed_by) == name.lower()
    ).first()
    if claim is None:
        return jsonify({"error": "That name doesn't match this claim"}), 403
    return jsonify({"claim_token": claim.claim_token})


@public_bp.route("/public/<token>/items/<int:item_id>/unclaim", methods=["POST"])
def unclaim_item(token, item_id):
    wishlist = get_public_list(token)
    if wishlist is None:
        return jsonify({"error": "Not found"}), 404
    gift = db.get_or_404(Gift, item_id)
    if gift.wishlist_id != wishlist.id:
        return jsonify({"error": "Not found"}), 404
    data = request.get_json()
    claim_token = data.get("claim_token")
    name = data.get("name", "").strip()

    claim = None
    if claim_token:
        claim = Claim.query.filter_by(gift_id=gift.id, claim_token=claim_token).first()
    if claim is None and name:
        claim = Claim.query.filter(
            Claim.gift_id == gift.id, db.func.lower(Claim.claimed_by) == name.lower()
        ).first()
    if claim is None:
        return jsonify({"error": "That name doesn't match this claim"}), 403

    db.session.delete(claim)
    db.session.commit()
    return jsonify(gift.to_dict(include_claim_status=True))


@public_bp.route("/public/<token>/items/<int:item_id>/purchased", methods=["POST"])
def set_purchased(token, item_id):
    wishlist = get_public_list(token)
    if wishlist is None:
        return jsonify({"error": "Not found"}), 404
    gift = db.get_or_404(Gift, item_id)
    if gift.wishlist_id != wishlist.id:
        return jsonify({"error": "Not found"}), 404
    data = request.get_json()
    claim = Claim.query.filter_by(gift_id=gift.id, claim_token=data.get("claim_token")).first()
    if claim is None:
        return jsonify({"error": "Claim it first"}), 400
    claim.purchased = bool(data.get("purchased", True))
    db.session.commit()
    return jsonify(gift.to_dict(include_claim_status=True))
