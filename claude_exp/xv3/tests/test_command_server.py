import logging
import threading

from shared.command_server import CommandServer
from shared.stats import Stats


def make_server(auth_token=None):
    stats = Stats()
    stop_event = threading.Event()
    cmd = CommandServer(port=0, stats=stats, stop_event=stop_event, auth_token=auth_token)
    return cmd, stats, stop_event


def test_stats_route_unprotected():
    cmd, stats, _ = make_server()
    stats.record_sent()
    client = cmd.app.test_client()

    resp = client.get("/stats")
    assert resp.status_code == 200
    assert resp.get_json()["sent_total"] == 1


def test_stop_route_protected_no_token_set():
    cmd, _, stop_event = make_server(auth_token=None)
    client = cmd.app.test_client()

    resp = client.post("/stop")
    assert resp.status_code == 200
    assert resp.get_json()["status"] == "stopping"
    assert stop_event.is_set()


def test_stop_route_protected_with_token():
    cmd, _, stop_event = make_server(auth_token="secret")
    client = cmd.app.test_client()

    resp = client.post("/stop")
    assert resp.status_code == 403
    assert not stop_event.is_set()

    resp = client.post("/stop", headers={"X-Router-Auth": "wrong"})
    assert resp.status_code == 403
    assert not stop_event.is_set()

    resp = client.post("/stop", headers={"X-Router-Auth": "secret"})
    assert resp.status_code == 200
    assert stop_event.is_set()


def test_log_level_get_and_post():
    cmd, _, _ = make_server(auth_token="secret")
    client = cmd.app.test_client()
    logging.getLogger().setLevel(logging.INFO)

    resp = client.get("/log_level")
    assert resp.get_json()["level"] == "INFO"

    # POST without auth fails
    resp = client.post("/log_level", json={"level": "DEBUG"})
    assert resp.status_code == 403

    resp = client.post(
        "/log_level", json={"level": "DEBUG"}, headers={"X-Router-Auth": "secret"}
    )
    assert resp.status_code == 200
    assert resp.get_json()["level"] == "DEBUG"

    resp = client.get("/log_level")
    assert resp.get_json()["level"] == "DEBUG"
    logging.getLogger().setLevel(logging.INFO)


def test_logs_route_json_and_text():
    cmd, _, _ = make_server()
    client = cmd.app.test_client()

    logging.getLogger().setLevel(logging.DEBUG)
    logger = logging.getLogger("test_command_server_logger")
    logger.debug("hello from test")

    resp = client.get("/logs")
    assert resp.status_code == 200
    lines = resp.get_json()
    assert any("hello from test" in line for line in lines)

    resp = client.get("/logs?format=text")
    assert resp.status_code == 200
    assert "hello from test" in resp.get_data(as_text=True)
    logging.getLogger().removeHandler(cmd.log_buffer)


def test_register_custom_route_protected():
    cmd, _, _ = make_server(auth_token="secret")

    @cmd.register("/custom", methods=["GET"], protected=True)
    def custom():
        from flask import jsonify

        return jsonify({"ok": True})

    client = cmd.app.test_client()
    resp = client.get("/custom")
    assert resp.status_code == 403

    resp = client.get("/custom", headers={"X-Router-Auth": "secret"})
    assert resp.status_code == 200
    assert resp.get_json()["ok"] is True


def test_register_custom_route_unprotected():
    cmd, _, _ = make_server(auth_token="secret")

    @cmd.register("/open", methods=["GET"])
    def open_route():
        from flask import jsonify

        return jsonify({"ok": True})

    client = cmd.app.test_client()
    resp = client.get("/open")
    assert resp.status_code == 200
