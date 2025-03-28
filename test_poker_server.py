import warnings
# Suppress the specific deprecation warning coming from ws_handler.
warnings.filterwarnings(
    "ignore", message="remove second argument of ws_handler", category=DeprecationWarning
)

import asyncio
import json
import unittest
import threading
import time

import uvicorn
from fastapi.testclient import TestClient
from starlette.testclient import WebSocketTestSession
from websockets import connect

from server import PokerServer, app, GAME_START_DELAY, server  # Imported global "server"


async def expect_message(ws: WebSocketTestSession, expected_type: str, timeout: float = 1.0):
    """
    Helper function to receive a message from the websocket within `timeout` seconds,
    parse it as JSON, assert its "type" matches expected_type, and return the parsed message.

    This helper supports both asynchronous websocket connections (e.g. from websockets.connect)
    as well as synchronous TestClient websockets (wrapped via asyncio.to_thread).
    """
    try:
        # If ws.receive_text is a coroutine function, call it directly.
        if asyncio.iscoroutinefunction(ws.receive_text):
            text = await asyncio.wait_for(ws.receive_text(), timeout)
        else:
            # Otherwise, run the synchronous receive_text in a thread.
            text = await asyncio.wait_for(asyncio.to_thread(ws.receive_text), timeout)
    except asyncio.TimeoutError:
        raise TimeoutError(
            f"Timed out waiting for message of type '{expected_type}' after {timeout} seconds"
        )
    msg = json.loads(text)
    assert msg["type"] == expected_type, f"Expected message type '{expected_type}', got '{msg['type']}' ({msg})"
    return msg


class TestPokerServer(unittest.IsolatedAsyncioTestCase):

    @classmethod
    def setUpClass(cls):
        # Start the Uvicorn server in a background thread for the duration of the tests.
        cls.config = uvicorn.Config(app, host="127.0.0.1", port=8000, log_level="info")
        cls.uvicorn_server = uvicorn.Server(cls.config)
        cls.server_thread = threading.Thread(target=cls.uvicorn_server.run, daemon=True)
        cls.server_thread.start()
        # Pause shortly to allow the server time to start.
        time.sleep(1)

    @classmethod
    def tearDownClass(cls):
        # Signal the server to shut down and wait for the thread to exit.
        cls.uvicorn_server.should_exit = True
        cls.server_thread.join()

    def setUp(self):
        # Reset the server state between tests to avoid interference
        server.reset_state()
        self.client = TestClient(app)

    async def websocket_connect(self, player_name, game_id=None):
        uri = f"ws://127.0.0.1:8000/ws/{player_name}"
        if game_id:
            uri += f"?game_id={game_id}"
        websocket = await connect(uri)
        return websocket

    async def test_play_game(self):
        player_names = ["Alice", "Bob", "Charlie", "David"]
        # Connect players using an asynchronous (external) connection.
        websockets = [await self.websocket_connect(name) for name in player_names]

        # Each player bets 100 chips in each round (simulate 3 rounds).
        for _ in range(3):
            for ws in websockets:
                await ws.send(json.dumps({"action": "bet", "amount": 100}))
                response = await ws.recv()

        # Close connections.
        for ws in websockets:
            await ws.close()

    async def test_valid_and_invalid_actions(self):
        client = TestClient(app)
        # Use distinct player names to help with debugging.
        with client.websocket_connect("/ws/TestAlice") as ws_alice, \
             client.websocket_connect("/ws/TestBob") as ws_bob, \
             client.websocket_connect("/ws/TestCharlie") as ws_charlie:

            msg_alice = await expect_message(ws_alice, "table_assigned")
            msg_bob   = await expect_message(ws_bob, "table_assigned")
            msg_charlie = await expect_message(ws_charlie, "table_assigned")
            table_id = msg_alice["table_id"]
            assert msg_bob["table_id"] == table_id
            assert msg_charlie["table_id"] == table_id, (table_id, msg_charlie)

            # Then, after joining, a "table_update" broadcast is sent.
            _ = await expect_message(ws_alice, "table_update")
            _ = await expect_message(ws_bob, "table_update")
            _ = await expect_message(ws_alice, "table_update")
            _ = await expect_message(ws_charlie, "table_update")
            _ = await expect_message(ws_alice, "table_update")

            # --- Game start broadcast -----------
            # Use the GAME_START_DELAY from configuration plus a 1-second overhead.
            start_timeout = GAME_START_DELAY + 1
            start_msg_alice = await expect_message(ws_alice, "start", timeout=start_timeout)
            start_msg_bob   = await expect_message(ws_bob, "start")
            _ = await expect_message(ws_charlie, "start")
            assert start_msg_alice["message"] == "Game is starting!", f"Expected 'Game is starting!', got {start_msg_alice['message']}"
            assert start_msg_bob["message"] == "Game is starting!", f"Expected 'Game is starting!', got {start_msg_bob['message']}"

            # Depending on timing, Charlie might receive either a "start" or "table_update" message.
            charlie_next = json.loads(await asyncio.to_thread(ws_charlie.receive_text))
            if charlie_next["type"] not in ["start", "table_update"]:
                raise AssertionError("Expected 'start' or 'table_update' for Charlie, got " + charlie_next["type"])

            # Retrieve the update broadcast to determine the current turn.
            update_msg_alice = await expect_message(ws_alice, "update")
            update_msg_bob   = await expect_message(ws_bob, "update")
            current_turn = update_msg_alice.get("current_turn")
            assert current_turn is not None, "Game state did not indicate a current turn."

            # --- Test invalid action: out-of-turn bet -----------
            if current_turn != "TestAlice":
                out_of_turn_ws = ws_alice
            else:
                out_of_turn_ws = ws_bob

            out_of_turn_ws.send_text(json.dumps({
                "action": "bet",
                "amount": 50
            }))
            error_msg = await expect_message(out_of_turn_ws, "error")
            assert "not your turn" in error_msg["message"].lower(), f"Error did not indicate out-of-turn: {error_msg['message']}"

            # --- Test invalid action: bet exceeding chips -----------
            if current_turn == "TestAlice":
                current_turn_ws = ws_alice
            elif current_turn == "TestBob":
                current_turn_ws = ws_bob
            elif current_turn == "TestCharlie":
                current_turn_ws = ws_charlie
            else:
                raise AssertionError("Unexpected current turn value.")

            current_turn_ws.send_text(json.dumps({
                "action": "bet",
                "amount": 10000  # An amount far beyond the available chips.
            }))
            error_msg = await expect_message(current_turn_ws, "error")
            assert "insufficient" in error_msg["message"].lower(), f"Expected insufficient chips error, got: {error_msg['message']}"

            # --- Test valid action: correct bet -----------
            current_turn_ws.send_text(json.dumps({
                "action": "bet",
                "amount": 100
            }))

            update_alice = json.loads(await asyncio.to_thread(ws_alice.receive_text))
            update_bob   = json.loads(await asyncio.to_thread(ws_bob.receive_text))
            update_charlie = json.loads(await asyncio.to_thread(ws_charlie.receive_text))

            for upd_msg in [update_alice, update_bob, update_charlie]:
                assert upd_msg["type"] == "update", f"Expected 'update' message; got {upd_msg['type']}"
                assert f"bets 100 chips" in upd_msg["message"].lower(), f"Update message did not confirm the bet: {upd_msg['message']}"


if __name__ == "__main__":
    unittest.main()