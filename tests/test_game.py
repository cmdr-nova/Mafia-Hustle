from mafia_hustle.extensions import db
from mafia_hustle.models import Event, Holding


def act(client, name, **body):
    response = client.post(f"/api/do/{name}", json=body)
    assert response.status_code == 200, response.get_data(as_text=True)
    return response.get_json()


def test_state_has_everything_the_screen_needs(client, make_user, login):
    login(make_user("vito"))
    data = client.get("/api/state").get_json()
    assert data["player"]["username"] == "vito"
    assert data["bars"]["health"] == {"value": 100, "max": 100, "next_in": None, "every": 20}
    assert data["bars"]["energy"]["value"] == 20
    assert {j["key"] for j in data["jobs"]} >= {"numbers", "crowd"}
    assert data["player"]["attack"] == data["player"]["base_attack"] == 5
    assert "money" not in client.get("/api/leaderboard").get_json()["leaderboard"][0]


def test_leaderboard_is_ordered_by_kills_then_level(client, make_user):
    make_user("vito", kills=1)
    make_user("michael", kills=5)
    make_user("tom", kills=1, level=9)
    names = [p["username"] for p in client.get("/api/leaderboard").get_json()["leaderboard"]]
    assert names == ["michael", "tom", "vito"]


def test_job(client, make_user, login):
    user = make_user("vito")
    login(user)
    data = act(client, "job", job="numbers")
    assert data["ok"]
    assert data["state"]["bars"]["energy"]["value"] == 19
    assert data["state"]["player"]["jobs_done"] == 1
    assert not act(client, "job", job="nope")["ok"]


def test_robbery_job_leaves_word_on_the_wire(client, make_user, login):
    user, mark = make_user("vito", level=2), make_user("fredo")
    login(user)
    act(client, "job", job="crowd")
    events = db.session.scalars(db.select(Event).where(Event.user_id == mark.id)).all()
    assert len(events) == 1 and "pocket" in events[0].text


def test_attack_by_id(client, make_user, login):
    attacker, defender = make_user("vito", attack=50), make_user("sonny", defense=1)
    login(attacker)
    data = act(client, "attack", defender_id=defender.id)
    assert data["ok"]
    assert defender.health < 100
    assert defender.fights_lost == 1
    assert data["state"]["bars"]["stamina"]["value"] == 9
    assert db.session.scalar(db.select(Event.text).where(Event.user_id == defender.id))


def test_attack_unknown_player(client, make_user, login):
    login(make_user("vito"))
    for bad in (999, "1", True, None):
        data = act(client, "attack", defender_id=bad)
        assert not data["ok"] and "not found" in data["message"]


def test_self_attack_is_refused(client, make_user, login):
    user = make_user("vito")
    login(user)
    assert "yourself" in act(client, "attack", defender_id=user.id)["message"]


def test_shopping_and_rackets(client, make_user, login):
    user = make_user("vito", money=3000)
    login(user)
    data = act(client, "buy", item="knuckles")
    assert data["ok"] and data["state"]["loadout"] == {"weapon": "knuckles"}
    assert data["state"]["player"]["attack"] == 7
    data = act(client, "buy", item="shoeshine")
    assert data["ok"] and data["state"]["income"]["per_hour"] == 40
    assert data["state"]["player"]["money"] == 3000 - 400 - 1500
    assert not act(client, "buy", item="knuckles")["ok"]
    assert not act(client, "buy", item="moon")["ok"]
    owned = dict(db.session.execute(db.select(Holding.item, Holding.quantity)).all())
    assert owned == {"knuckles": 1, "shoeshine": 1}


def test_collect_with_nothing_waiting(client, make_user, login):
    login(make_user("vito"))
    assert not act(client, "collect")["ok"]


def test_bank(client, make_user, login):
    login(make_user("vito"))
    data = act(client, "bank", direction="deposit", amount=500)
    assert data["state"]["player"]["bank"] == 450
    assert data["state"]["player"]["money"] == 500
    assert act(client, "bank", direction="withdraw", amount=450)["ok"]
    assert not act(client, "bank", direction="deposit", amount="500")["ok"]
    assert not act(client, "bank", direction="sideways", amount=5)["ok"]


def test_skill(client, make_user, login):
    login(make_user("vito", skill_points=1))
    data = act(client, "skill", skill="defense")
    assert data["state"]["player"]["defense"] == 6
    assert data["state"]["player"]["skill_points"] == 0


def test_hospital(client, make_user, login):
    user = make_user("vito", health=50)
    login(user)
    data = act(client, "hospital")
    assert data["ok"] and data["state"]["bars"]["health"]["value"] == 100


def test_unknown_action(client, make_user, login):
    login(make_user("vito"))
    assert client.post("/api/do/launder").status_code == 404


def test_targets_are_alive_and_not_you(client, make_user, login):
    me = make_user("vito")
    make_user("sonny")
    make_user("luca", health=0)
    login(me)
    names = {t["username"] for t in client.get("/api/targets").get_json()["targets"]}
    assert names == {"sonny"}


def test_favicon(client):
    response = client.get("/favicon.ico")
    assert response.status_code == 200
    assert response.mimetype == "image/svg+xml"


def test_profile_shows_who_you_are_on_your_network(client, make_user, login):
    user = make_user(
        "@vito@fedi.example.org", display_name="Vito", avatar_url="https://fedi.example.org/a.png"
    )
    login(user)
    page = client.get("/").get_data(as_text=True)
    assert 'src="https://fedi.example.org/a.png"' in page
    assert 'href="https://fedi.example.org/@vito"' in page
    assert "Fediverse" in page


def test_profile_url():
    from types import SimpleNamespace

    from mafia_hustle.game import profile_url

    def url(provider, username):
        return profile_url(SimpleNamespace(provider=provider, username=username))

    assert url("fediverse", "@vito@fedi.example.org") == "https://fedi.example.org/@vito"
    assert url("bluesky", "vito.bsky.social") == "https://bsky.app/profile/vito.bsky.social"
    assert url("fediverse", "@vito@evil.example/../x") is None
    assert url("bluesky", "javascript:alert(1)") is None
    assert url("bot", "Knuckles Malone") is None


def test_leaderboard_pins_your_rank_when_outside_the_top_ten(client, make_user, login):
    for i in range(12):
        make_user(f"hitter{i}", kills=10 + i)
    tied = make_user("tied", kills=1)
    me = make_user("me", kills=1)
    login(me)
    data = client.get("/api/leaderboard").get_json()
    assert len(data["leaderboard"]) == 10
    assert data["me"]["username"] == "me"
    assert data["me"]["rank"] == 13  # tied with "tied", behind the 12 hitters
    assert "money" not in data["me"]

    login(tied)
    assert client.get("/api/leaderboard").get_json()["me"]["rank"] == 13


def test_no_pinned_rank_inside_the_top_ten_or_logged_out(client, make_user, login):
    star = make_user("star", kills=99)
    assert client.get("/api/leaderboard").get_json()["me"] is None
    login(star)
    assert client.get("/api/leaderboard").get_json()["me"] is None


def test_rank_breaks_kill_ties_by_level_then_points(make_user):
    from mafia_hustle.game import rank_of

    make_user("a", kills=2, level=3, points=50)
    b = make_user("b", kills=2, level=3, points=10)
    c = make_user("c", kills=2, level=1, points=999)
    assert (rank_of(b), rank_of(c)) == (2, 3)
