import pytest

from withings_wpp import account


def test_login_params_never_hash_password():
    p = account.login_params("user@example.com", "pw")
    assert p["password"] == "pw" and p["authprovider"] == "withings" and "hash" not in p


def test_parse_login():
    assert account.parse_login({"status": 0, "body": {"sessionid": "abc"}}) == "abc"
    with pytest.raises(account.InvalidCredentials):
        account.parse_login({"status": 100})
    with pytest.raises(account.AccountError):
        account.parse_login({"status": 0, "body": {}})


def test_parse_scales_filters_model_and_kl():
    resp = {
        "status": 0,
        "body": {
            "associations": [
                {"deviceid": 1, "kl": "k1", "deviceproperties": {"model": 16, "macaddress": "00:11:22:33:44:55"}},
                {"deviceid": 2, "kl": "k2", "deviceproperties": {"model": 93}},
                {"deviceid": 3, "deviceproperties": {"model": 16}},
            ]
        },
    }
    (s,) = account.parse_scales(resp)
    assert (s.deviceid, s.model, s.mac, s.kl) == (1, 16, "00:11:22:33:44:55", "k1")
    assert len(account.parse_scales(resp, model=None)) == 2


def test_parse_users_and_accountid():
    resp = {"status": 0, "body": {"users": [{"id": 1001, "firstname": "Alice"}, {"id": 1002, "firstname": ""}]}}
    assert account.parse_users(resp) == {1001: "Alice", 1002: "User 1002"}
    scales = account.parse_scales(
        {"status": 0, "body": {"associations": [{"accountid": 77, "kl": "k", "deviceproperties": {"model": 16}}]}}
    )
    assert scales[0].accountid == 77
