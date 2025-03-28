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
from websockets import connect

from server import PokerServer, app, GAME_START_DELAY, server  # Imported global "server"


async def read_message(ws, timeout: float = 1.0) -> tuple[dict | None, Exception | None]:
    """
    Reads a message from the websocket and returns a tuple (message, error).
    - If the message is successfully received and parsed, returns (message, None).
    - If a TimeoutError occurs or JSON parsing fails, returns (None, error).
    """
    try:
        text = await asyncio.wait_for(ws.recv(), timeout)
    except asyncio.TimeoutError as e:
        return None, e

    try:
        msg = json.loads(text)
        return msg, None
    except Exception as e:
        return None, e


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

    async def websocket_connect(self, player_name, game_id=None):
        # Build the URI; use a query parameter named game_id if provided.
        uri = f"ws://127.0.0.1:8000/ws/{player_name}"
        if game_id:
            uri += f"?game_id={game_id}"
        websocket = await connect(uri)
        return websocket

    # async def test_play_game(self):
    #     player_names = ["Alice", "Bob", "Charlie", "David"]
    #     # Connect players using an asynchronous (external) connection.
    #     websockets = [await self.websocket_connect(name) for name in player_names]

    #     # Each player bets 100 chips in each round (simulate 3 rounds).
    #     for _ in range(3):
    #         for ws in websockets:
    #             await ws.send(json.dumps({"action": "bet", "amount": 100}))
    #             response = await ws.recv()

    #     # Close connections.
    #     for ws in websockets:
    #         await ws.close()

    async def test_valid_and_invalid_actions(self):
        # Connect players using fully asynchronous websockets.
        ws_alice = await self.websocket_connect("TestAlice")
        ws_bob = await self.websocket_connect("TestBob")
        ws_charlie = await self.websocket_connect("TestCharlie")

        try:
            # table_assigned messages
            msg_alice, err = await read_message(ws_alice)
            assert err is None, f"Error receiving message for Alice: {type(err)} {err}"
            assert msg_alice.get("type") == "table_assigned", f"Expected 'table_assigned', got {msg_alice}"

            msg_bob, err = await read_message(ws_bob)
            assert err is None, f"Error receiving message for Bob: {type(err)} {err}"
            assert msg_bob.get("type") == "table_assigned", f"Expected 'table_assigned', got {msg_bob}"

            msg_charlie, err = await read_message(ws_charlie)
            assert err is None, f"Error receiving message for Charlie: {type(err)} {err}"
            assert msg_charlie.get("type") == "table_assigned", f"Expected 'table_assigned', got {msg_charlie}"

            table_id = msg_alice["table_id"]
            assert msg_bob["table_id"] == table_id
            assert msg_charlie["table_id"] == table_id, f"Expected table id {table_id}, got {msg_charlie}"

            # table_update broadcasts after joins: Alice gets 3, Bob gets 2, Charlie gets 1.
            msg, err = await read_message(ws_alice)
            assert err is None, f"Error receiving table_update for Alice: {type(err)} {err}"
            assert msg.get("type") == "table_update", f"Expected 'table_update', got {msg}"
            msg, err = await read_message(ws_alice)
            assert err is None, f"Error receiving second table_update for Alice: {type(err)} {err}"
            assert msg.get("type") == "table_update", f"Expected 'table_update', got {msg}"
            msg, err = await read_message(ws_alice)
            assert err is None, f"Error receiving second table_update for Alice: {type(err)} {err}"
            assert msg.get("type") == "table_update", f"Expected 'table_update', got {msg}"

            # table_update broadcasts after joins: Alice gets 3, Bob gets 2, Charlie gets 1.
            msg, err = await read_message(ws_bob)
            assert err is None, f"Error receiving table_update for Bob: {type(err)} {err}"
            assert msg.get("type") == "table_update", f"Expected 'table_update', got {msg}"
            msg, err = await read_message(ws_bob)
            assert err is None, f"Error receiving table_update for Bob: {type(err)} {err}"
            assert msg.get("type") == "table_update", f"Expected 'table_update', got {msg}"

            # table_update broadcasts after joins: Alice gets 3, Bob gets 2, Charlie gets 1.
            msg, err = await read_message(ws_charlie)
            assert err is None, f"Error receiving table_update for Charlie: {type(err)} {err}"
            assert msg.get("type") == "table_update", f"Expected 'table_update', got {msg}"

            # --- Wait for Game Start Broadcast -----------
            start_timeout = GAME_START_DELAY + 1
            print("[DEBUG] Waiting for 'start' message...")
            start_msg_alice, err = await read_message(ws_alice, timeout=start_timeout)
            assert err is None, f"Error receiving start message for Alice: {type(err)} {err}"
            assert start_msg_alice.get("type") == "start", f"Expected 'start', got {start_msg_alice}"
            assert start_msg_alice.get("message") == "Game is starting!", f"Unexpected start message: {start_msg_alice}"

            start_msg_bob, err = await read_message(ws_bob, timeout=start_timeout)
            assert err is None, f"Error receiving start message for Bob: {type(err)} {err}"
            assert start_msg_bob.get("type") == "start", f"Expected 'start', got {start_msg_bob}"
            assert start_msg_bob.get("message") == "Game is starting!", f"Unexpected start message: {start_msg_bob}"

            start_msg_charlie, err = await read_message(ws_charlie, timeout=start_timeout)
            assert err is None, f"Error receiving start message for Charlie: {type(err)} {err}"
            assert start_msg_charlie.get("type") == "start", f"Expected 'start', got {start_msg_charlie}"
            assert start_msg_charlie.get("message") == "Game is starting!", f"Unexpected start message: {start_msg_charlie}"

            # Update broadcast to determine current turn.
            update_msg_alice, err = await read_message(ws_alice)
            assert err is None, f"Error receiving update for Alice: {type(err)} {err}"
            assert update_msg_alice.get("type") == "update", f"Expected 'update', got {update_msg_alice}"

            update_msg_bob, err = await read_message(ws_bob)
            assert err is None, f"Error receiving update for Bob: {type(err)} {err}"
            assert update_msg_bob.get("type") == "update", f"Expected 'update', got {update_msg_bob}"

            current_turn = update_msg_alice.get("current_turn")
            assert current_turn is not None, "Game state did not indicate a current turn."

            # --- Test invalid action: out-of-turn bet -----------
            if current_turn != "TestAlice":
                out_of_turn_ws = ws_alice
            else:
                out_of_turn_ws = ws_bob

            out_of_turn_ws.send(json.dumps({
                "action": "bet",
                "amount": 50
            }))
            error_msg, err = await read_message(out_of_turn_ws)
            assert err is None, f"Error receiving error for out-of-turn bet: {type(err)} {err}"
            assert error_msg.get("type") == "error", f"Expected error type, got {error_msg}"
            assert "not your turn" in error_msg.get("message", "").lower(), f"Error did not indicate out-of-turn: {error_msg.get('message')}"

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
            error_msg, err = await read_message(current_turn_ws)
            assert err is None, f"Error receiving error for excessive bet: {type(err)} {err}"
            assert error_msg.get("type") == "error", f"Expected error type, got {error_msg}"
            assert "insufficient" in error_msg.get("message", "").lower(), f"Expected insufficient chips error, got: {error_msg.get('message')}"

            # --- Test valid action: correct bet -----------
            current_turn_ws.send_text(json.dumps({
                "action": "bet",
                "amount": 100
            }))

            update_alice_raw, err = await read_message(ws_alice)
            assert err is None, f"Error receiving update for Alice after bet: {type(err)} {err}"
            update_bob_raw, err = await read_message(ws_bob)
            assert err is None, f"Error receiving update for Bob after bet: {type(err)} {err}"
            update_charlie_raw, err = await read_message(ws_charlie)
            assert err is None, f"Error receiving update for Charlie after bet: {type(err)} {err}"

            for upd_msg in [update_alice_raw, update_bob_raw, update_charlie_raw]:
                assert upd_msg.get("type") == "update", f"Expected 'update' message; got {upd_msg.get('type')}"
                assert "bets 100 chips" in upd_msg.get("message", "").lower(), f"Update message did not confirm the bet: {upd_msg.get('message')}"

        finally:
            # Ensure websockets are properly closed.
            await ws_alice.close()
            await ws_bob.close()
            await ws_charlie.close()


if __name__ == "__main__":
    unittest.main()