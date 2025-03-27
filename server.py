from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from typing import List, Dict, Any
import json

app = FastAPI()

class PokerServer:
    def __init__(self):
        self.active_games: Dict[str, TexasHoldEm] = {}
        self.connections: Dict[str, List[WebSocket]] = {}
    
    async def connect(self, game_id: str, websocket: WebSocket):
        await websocket.accept()
        if game_id not in self.connections:
            self.connections[game_id] = []
        self.connections[game_id].append(websocket)
    
    def create_game(self, game_id: str, players: List[str]):
        self.active_games[game_id] = TexasHoldEm(players)
    
    async def broadcast(self, game_id: str, message: Any):
        if game_id in self.connections:
            for connection in self.connections[game_id]:
                await connection.send_text(json.dumps(message))
    
    async def handle_action(self, game_id: str, player_name: str, action: str, amount: int = 0):
        game = self.active_games.get(game_id)
        if not game:
            return
        
        player = next((p for p in game.players if p.name == player_name), None)
        if not player:
            return
        
        if action == "bet":
            player.chips -= amount
            player.current_bet += amount
            game.pot += amount
        elif action == "fold":
            player.active = False
        
        await self.broadcast(game_id, {"type": "update", "players": [str(p) for p in game.players], "pot": game.pot})

server = PokerServer()

@app.websocket("/ws/{game_id}/{player_name}")
async def websocket_endpoint(websocket: WebSocket, game_id: str, player_name: str):
    await server.connect(game_id, websocket)
    try:
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)
            await server.handle_action(game_id, player_name, message["action"], message.get("amount", 0))
    except WebSocketDisconnect:
        server.connections[game_id].remove(websocket)
