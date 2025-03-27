import asyncio
import json
import unittest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from websockets import connect

from server import PokerServer  # Adjust the import based on your project structure

class TestPokerServer(unittest.TestCase):
    def setUp(self):
        self.server = PokerServer()
        self.app = FastAPI()
        self.client = TestClient(self.app)

    async def websocket_connect(self, player_name, game_id=None):
        uri = f"ws://localhost:8000/ws/{player_name}"
        if game_id:
            uri += f"?game_id={game_id}"
        websocket = await connect(uri)
        return websocket

    async def play_game(self, player_names):
        # Connect players
        websockets = [await self.websocket_connect(name) for name in player_names]

        # Each player bets 100 chips in each round
        for _ in range(3):  # Simulate 3 betting rounds
            for ws in websockets:
                await ws.send(json.dumps({"action": "bet", "amount": 100}))
                response = await ws.recv()
                print(f"Response for {ws}: {response}")

        # Close connections
        for ws in websockets:
            await ws.close()

    def test_game_play(self):
        player_names = ["Alice", "Bob", "Charlie", "David"]
        asyncio.run(self.play_game(player_names))

if __name__ == "__main__":
    unittest.main()