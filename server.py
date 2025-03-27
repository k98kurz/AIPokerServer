from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from typing import List, Dict, Any
import json
import uuid
from game import TexasHoldEm


# This constant defines how many players are required to start a game.
MIN_PLAYERS = 2


class PokerServer:
    connections: Dict[str, Dict[str, WebSocket]]
    tables: Dict[str, Dict[str, List[str]]]
    active_games: Dict[str, TexasHoldEm]

    def __init__(self):
        self.active_games: Dict[str, TexasHoldEm] = {}
        # Maps table_id to {player_name: WebSocket}
        self.connections: Dict[str, Dict[str, WebSocket]] = {}
        # Each table has a list of seated players and waiting players.
        self.tables: Dict[str, Dict[str, List[str]]] = {}

    async def connect(self, table_id: str, player_name: str, websocket: WebSocket):
        await websocket.accept()
        if table_id not in self.connections:
            self.connections[table_id] = {}
        self.connections[table_id][player_name] = websocket

    def get_available_table(self) -> str:
        """
        Searches for an existing table that is not currently running a game.
        If none is found, generates a new table_id and initializes its seating.
        """
        for table_id in self.tables:
            if table_id not in self.active_games:
                return table_id
        # No suitable table found; create a new one.
        new_table_id = str(uuid.uuid4())
        self.tables[new_table_id] = {"players": [], "waiting": []}
        return new_table_id

    async def join_table(self, table_id: str, player_name: str):
        """
        Adds a player to the specified table. If a game is in progress at the table,
        the player is added to the waiting list.
        Otherwise the player is seated immediately. A table update is broadcast,
        and if there are enough seated players a new game is started.
        """
        if table_id not in self.tables:
            self.tables[table_id] = {"players": [], "waiting": []}

        # If a game is running at this table, new players wait for the next hand.
        if table_id in self.active_games:
            if (player_name not in self.tables[table_id]["waiting"] and
                player_name not in self.tables[table_id]["players"]):
                self.tables[table_id]["waiting"].append(player_name)
        else:
            if player_name not in self.tables[table_id]["players"]:
                self.tables[table_id]["players"].append(player_name)

        # Broadcast table seating state.
        await self.broadcast(table_id, {
            "type": "table_update",
            "players": self.tables[table_id]["players"],
            "waiting": self.tables[table_id]["waiting"]
        })

        # If there are enough seated players and no game is running, start the game.
        if len(self.tables[table_id]["players"]) >= MIN_PLAYERS and table_id not in self.active_games:
            self.create_game(table_id, self.tables[table_id]["players"])
            await self.broadcast(table_id, {
                "type": "start",
                "message": "Game is starting!"
            })
            game = self.active_games[table_id]
            game.start_game()
            # Broadcast the initial game state.
            await self.broadcast(table_id, {
                "type": "update",
                "players": [p.public_view() for p in game.players],
                "pot": game.pot,
                "phase": game.phase,
                "current_turn": game.players[game.current_turn_index].name,
                "community_cards": [str(card) for card in game.community_cards]
            })
            # Deal each player his private hand.
            for player in game.players:
                if player.name in self.connections[table_id]:
                    await self.connections[table_id][player.name].send_text(json.dumps({
                        "type": "hand",
                        "hand": [str(card) for card in player.hand]
                    }))

    def create_game(self, table_id: str, players: List[str]):
        """Creates a new game at a table with the list of players seated."""
        self.active_games[table_id] = TexasHoldEm(players)

    async def broadcast(self, table_id: str, message: Any):
        """Sends a message to all websocket connections for the given table_id."""
        if table_id in self.connections:
            for connection in self.connections[table_id].values():
                await connection.send_text(json.dumps(message))

    async def handle_action(self, table_id: str, player_name: str, action: str, amount: int = 0):
        game = self.active_games.get(table_id)
        if not game:
            return

        # Only process bet and fold actions via the game logic.
        if action not in ["bet", "fold"]:
            return

        success, message = game.take_action(player_name, action, amount)

        if not success:
            # Send an error message to the player who attempted the invalid action.
            if player_name in self.connections.get(table_id, {}):
                await self.connections[table_id][player_name].send_text(json.dumps({
                    "type": "error",
                    "message": message
                }))
            return

        await self.broadcast(table_id, {
            "type": "update",
            "message": message,
            "players": [p.public_view() for p in game.players],
            "pot": game.pot,
            "phase": game.phase,
            "current_turn": game.players[game.current_turn_index].name if game.players else None,
            "community_cards": [str(card) for card in game.community_cards]
        })

        # When the game reaches showdown, end the current game and, if there are waiting players,
        # start the next one.
        if game.phase == "showdown":
            await self.end_game_and_start_new_one(table_id)

    async def end_game_and_start_new_one(self, table_id: str):
        """
        Ends the active game on the table, merges any waiting players with the current seated players,
        and starts a new game if there are enough players.
        """
        game = self.active_games.get(table_id)
        if not game:
            return

        # End the current game.
        del self.active_games[table_id]

        # Merge waiting players into the next round.
        table = self.tables.get(table_id)
        if table:
            # Combine current seated players with waiting players (avoiding duplicates).
            new_players = table["players"] + table["waiting"]
            new_players = list(dict.fromkeys(new_players))
            self.tables[table_id]["players"] = new_players
            self.tables[table_id]["waiting"] = []

        if table and len(self.tables[table_id]["players"]) >= MIN_PLAYERS:
            self.create_game(table_id, self.tables[table_id]["players"])
            game = self.active_games[table_id]
            game.start_game()
            await self.broadcast(table_id, {
                "type": "start",
                "message": "New game is starting!"
            })
            await self.broadcast(table_id, {
                "type": "update",
                "players": [p.public_view() for p in game.players],
                "pot": game.pot,
                "phase": game.phase,
                "current_turn": game.players[game.current_turn_index].name,
                "community_cards": [str(card) for card in game.community_cards]
            })
            for player in game.players:
                if player.name in self.connections[table_id]:
                    await self.connections[table_id][player.name].send_text(json.dumps({
                        "type": "hand",
                        "hand": [str(card) for card in player.hand]
                    }))

    async def disconnect(self, table_id: str, player_name: str):
        # Remove the websocket connection.
        if table_id in self.connections:
            self.connections[table_id].pop(player_name, None)

        # Remove the player from the table—checking both to see if they are seated or waiting.
        if table_id in self.tables:
            if player_name in self.tables[table_id]["players"]:
                self.tables[table_id]["players"].remove(player_name)
            if player_name in self.tables[table_id]["waiting"]:
                self.tables[table_id]["waiting"].remove(player_name)
            await self.broadcast(table_id, {
                "type": "table_update",
                "players": self.tables[table_id]["players"],
                "waiting": self.tables[table_id]["waiting"]
            })


server = PokerServer()

app = FastAPI()

@app.websocket("/ws/{player_name}")
async def websocket_endpoint(websocket: WebSocket, player_name: str):
    # Use the "table_id" query parameter instead of "game_id."
    param_table_id = websocket.query_params.get("table_id")
    if param_table_id:
        table_id = param_table_id
    else:
        table_id = server.get_available_table()

    # Connect and join the table.
    await server.connect(table_id, player_name, websocket)
    await server.join_table(table_id, player_name)

    # Optionally let the client know which table (table_id) they were assigned to.
    if not param_table_id:
        await websocket.send_text(json.dumps({
            "type": "table_assigned",
            "table_id": table_id
        }))

    try:
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)
            await server.handle_action(
                table_id, player_name, message["action"], message.get("amount", 0)
            )
    except WebSocketDisconnect:
        await server.disconnect(table_id, player_name)
