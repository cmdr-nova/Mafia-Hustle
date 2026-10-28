def test_player_info(client, make_user, login):
    user = make_user("vito")
    login(user)
    data = client.get("/api/player-info").get_json()
    assert data["username"] == "vito"
    assert data["health"] == data["max_health"] == 100


def test_leaderboard_is_ordered_by_kills(client, make_user):
    make_user("vito", kills=1)
    make_user("michael", kills=5)
    names = [p["username"] for p in client.get("/api/leaderboard").get_json()["leaderboard"]]
    assert names == ["michael", "vito"]


def test_attack_by_id(client, make_user, login):
    attacker, defender = make_user("vito"), make_user("sonny")
    login(attacker)
    response = client.post("/api/attack", json={"defender_id": defender.id})
    assert response.status_code == 200
    assert defender.health == 90


def test_attack_unknown_player(client, make_user, login):
    login(make_user("vito"))
    assert client.post("/api/attack", json={"defender_id": 999}).status_code == 404
    assert client.post("/api/attack", json={"defender_id": "1"}).status_code == 404


def test_self_attack_is_refused(client, make_user, login):
    user = make_user("vito")
    login(user)
    data = client.post("/api/attack", json={"defender_id": user.id}).get_json()
    assert "yourself" in data["message"]


def test_run_job_and_heal(client, make_user, login):
    user = make_user("vito")
    make_user("fredo")
    login(user)
    assert client.post("/api/run-job").status_code == 200
    assert user.health < 100
    assert client.post("/api/heal-up").status_code == 200
