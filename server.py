from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from typing import List, Dict, Any
import json
import uuid
from game import TexasHoldEm


# This constant defines how many players are required to start a game.
MIN_PLAYERS = 2


class PokerServer:
    connections: Dict[str, Dict[str, WebSocket]]
    lobbies: Dict[str, List[str]]
    active_games: Dict[str, TexasHoldEm]

    def __init__(self):
        self.active_games: Dict[str, TexasHoldEm] = {}
        # Now a dictionary mapping game_id to a dict of {player_name: WebSocket}
        self.connections: Dict[str, Dict[str, WebSocket]] = {}
        self.lobbies: Dict[str, List[str]] = {}

    async def connect(self, game_id: str, player_name: str, websocket: WebSocket):
        await websocket.accept()
        if game_id not in self.connections:
            self.connections[game_id] = {}
        self.connections[game_id][player_name] = websocket

    def get_available_lobby(self) -> str:
        """
        Searches for an existing lobby that has at least one waiting player and has not started a game.
        If no such lobby is found, generates and returns a new game_id.
        """
        for lobby_id, players in self.lobbies.items():
            if lobby_id not in self.active_games and players:
                return lobby_id
        return str(uuid.uuid4())

    async def join_lobby(self, game_id: str, player_name: str):
        """
        Adds a player to the lobby. Broadcasts the lobby update to all players in the lobby,
        and if the number of players in the lobby reaches the minimum needed, starts the game.
        """
        if game_id not in self.lobbies:
            self.lobbies[game_id] = []
        if player_name not in self.lobbies[game_id]:
            self.lobbies[game_id].append(player_name)

        # Broadcast lobby update so that clients know who is waiting
        await self.broadcast(game_id, {
            "type": "lobby_update",
            "players": self.lobbies[game_id]
        })

        # If enough players are in the lobby and the game isn't already started, create and start the game.
        if len(self.lobbies[game_id]) >= MIN_PLAYERS and game_id not in self.active_games:
            self.create_game(game_id, self.lobbies[game_id])
            await self.broadcast(game_id, {
                "type": "start",
                "message": "Game is starting!"
            })
            # Start the game with proper enforcement of game rules.
            game = self.active_games[game_id]
            game.start_game()
            # Broadcast initial game state.
            await self.broadcast(game_id, {
                "type": "update",
                "players": [p.public_view() for p in game.players],
                "pot": game.pot,
                "phase": game.phase,
                "current_turn": game.players[game.current_turn_index].name,
                "community_cards": [str(card) for card in game.community_cards]
            })
            # Deal hands privately.
            for player in game.players:
                if player.name in self.connections[game_id]:
                    await self.connections[game_id][player.name].send_text(json.dumps({
                        "type": "hand",
                        "hand": [str(card) for card in player.hand]
                    }))

    def create_game(self, game_id: str, players: List[str]):
        """Creates a new game with the list of players from the lobby."""
        self.active_games[game_id] = TexasHoldEm(players)

    async def broadcast(self, game_id: str, message: Any):
        """Sends a message to all websocket connections for the given game_id."""
        if game_id in self.connections:
            for connection in self.connections[game_id].values():
                await connection.send_text(json.dumps(message))

    async def handle_action(self, game_id: str, player_name: str, action: str, amount: int = 0):
        game = self.active_games.get(game_id)
        if not game:
            return

        # Only process bet and fold actions via the game logic.
        if action not in ["bet", "fold"]:
            return

        success, message = game.take_action(player_name, action, amount)

        if not success:
            # Send an error message to the player who attempted the invalid action.
            if player_name in self.connections.get(game_id, {}):
                await self.connections[game_id][player_name].send_text(json.dumps({
                    "type": "error",
                    "message": message
                }))
            return

        # Broadcast the updated game state if the action succeeds.
        await self.broadcast(game_id, {
            "type": "update",
            "message": message,
            "players": [p.public_view() for p in game.players],
            "pot": game.pot,
            "phase": game.phase,
            "current_turn": game.players[game.current_turn_index].name if game.players else None,
            "community_cards": [str(card) for card in game.community_cards]
        })


server = PokerServer()

app = FastAPI()

@app.websocket("/ws/{player_name}")
async def websocket_endpoint(websocket: WebSocket, player_name: str):
    # Try to get the game_id from the query parameters. If not provided, assign one.
    param_game_id = websocket.query_params.get("game_id")
    if param_game_id:
        game_id = param_game_id
    else:
        game_id = server.get_available_lobby()

    # Connect and join the lobby for the assigned game_id.
    await server.connect(game_id, player_name, websocket)
    await server.join_lobby(game_id, player_name)

    # Optionally let the client know which lobby (game_id) they were assigned to.
    if not param_game_id:
        await websocket.send_text(json.dumps({
            "type": "lobby_assigned",
            "game_id": game_id
        }))

    try:
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)
            await server.handle_action(
                game_id, player_name, message["action"], message.get("amount", 0)
            )
    except WebSocketDisconnect:
        # Remove the websocket connection
        if game_id in server.connections:
            server.connections[game_id].pop(player_name, None)

        # Also remove the player from the lobby (if the game hasn't started yet)
        if game_id in server.lobbies and player_name in server.lobbies[game_id]:
            server.lobbies[game_id].remove(player_name)

        # Broadcast the updated lobby list to the remaining connections
        await server.broadcast(game_id, {
            "type": "lobby_update",
            "players": server.lobbies.get(game_id, [])
        })
