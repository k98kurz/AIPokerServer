from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from typing import List, Dict, Any
import json
import uuid
from game import TexasHoldEm
import asyncio  # <-- add asyncio import if not already present


# This constant defines how many players are required to start a game.
MIN_PLAYERS = 2
MAX_PLAYERS = 6

# Configurable delay (in seconds) before the first game starts after reaching the minimum number of players.
GAME_START_DELAY = 5


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
        # Configurable delay before starting the game.
        self.game_start_delay = GAME_START_DELAY
        # Dictionary mapping table_id to scheduled delayed start tasks.
        self.start_tasks: Dict[str, asyncio.Task] = {}

    def reset_state(self):
        """Reset the internal state (useful for tests)."""
        self.active_games.clear()
        self.connections.clear()
        self.tables.clear()
        # Cancel any scheduled start tasks.
        for task in self.start_tasks.values():
            task.cancel()
        self.start_tasks.clear()

    async def connect(self, table_id: str, player_name: str, websocket: WebSocket):
        await websocket.accept()
        if table_id not in self.connections:
            self.connections[table_id] = {}
        self.connections[table_id][player_name] = websocket

    def get_available_table(self) -> str:
        """
        Searches for an existing table that is not full.
        A table is considered full if the total number of players
        (seated + waiting) reaches MAX_PLAYERS.
        If no such table is found, generates a new table_id and initializes its seating.
        """
        for table_id, table_info in self.tables.items():
            total_players = len(table_info["players"]) + len(table_info["waiting"])
            if total_players < MAX_PLAYERS:
                return table_id
        # No suitable table found; create a new one.
        new_table_id = str(uuid.uuid4())
        self.tables[new_table_id] = {"players": [], "waiting": []}
        return new_table_id

    async def join_table(self, table_id: str, player_name: str):
        """
        Adds a player to the specified table. If a game is in progress at the table,
        the player is added to the waiting list.
        Otherwise the player is seated immediately.
        Sends a table_assigned message to the player,
        broadcasts a table_update and if there are enough seated players, schedules a delayed game start.
        """
        if table_id not in self.tables:
            self.tables[table_id] = {"players": [], "waiting": []}

        # Process seating based on whether a game is in progress.
        if table_id in self.active_games:
            if (player_name not in self.tables[table_id]["waiting"] and
                player_name not in self.tables[table_id]["players"]):
                self.tables[table_id]["waiting"].append(player_name)
        else:
            if player_name not in self.tables[table_id]["players"]:
                self.tables[table_id]["players"].append(player_name)

        # Always send the table_assigned message to the player.
        if player_name in self.connections.get(table_id, {}):
            await self.connections[table_id][player_name].send_text(json.dumps({
                "type": "table_assigned",
                "table_id": table_id
            }))

        print(f"[DEBUG] Player '{player_name}' joined table {table_id}. Current seated players: {self.tables[table_id]['players']}")
        # Broadcast table seating state.
        await self.broadcast(table_id, {
            "type": "table_update",
            "players": self.tables[table_id]["players"],
            "waiting": self.tables[table_id]["waiting"]
        })

        # Instead of immediately starting the game, schedule a delayed start.
        if (len(self.tables[table_id]["players"]) >= MIN_PLAYERS and
            table_id not in self.active_games):
            if table_id not in self.start_tasks:
                print(f"[DEBUG] Scheduling game start for table {table_id}")
                self.start_tasks[table_id] = asyncio.create_task(self.delayed_game_start(table_id))

    def create_game(self, table_id: str, players: List[str]):
        """Creates a new game at a table with the list of players seated."""
        self.active_games[table_id] = TexasHoldEm(players)

    async def delayed_game_start(self, table_id: str):
        """
        Waits for a configurable amount of time before starting the game.
        If after waiting the table still has enough players and no game has started,
        the game is created and started.
        """
        print(f"[DEBUG] Delayed game start called for table {table_id}. Waiting for {self.game_start_delay} seconds. Current players: {self.tables.get(table_id, {}).get('players', [])}")
        await asyncio.sleep(self.game_start_delay)
        if table_id not in self.tables:
            print(f"[DEBUG] Table {table_id} not found after sleep.")
            return
        players = self.tables[table_id]["players"]
        print(f"[DEBUG] After waiting, table {table_id} players: {players}")
        if len(players) >= MIN_PLAYERS and table_id not in self.active_games:
            print(f"[DEBUG] Starting game for table {table_id} with players: {players}")
            self.create_game(table_id, players)
            game = self.active_games[table_id]
            game.start_game()
            await self.broadcast(table_id, {
                "type": "start",
                "message": "Game is starting!"
            })
            await self.broadcast(table_id, {
                "type": "update",
                "players": [p.public_view() for p in game.players],
                "pot": game.pot,
                "phase": game.phase,
                "current_turn": game.players[game.current_turn_index].name if game.players else None,
                "community_cards": [str(card) for card in game.community_cards]
            })
            # *** Send each player their private hand ***
            for player in game.players:
                if player.name in self.connections.get(table_id, {}):
                    await self.connections[table_id][player.name].send_text(json.dumps({
                        "type": "hand",
                        "hand": [str(card) for card in player.hand]
                    }))
        else:
            print(f"[DEBUG] Not starting game for table {table_id}. Insufficient players or game already active. Current players: {players}")
        # Remove the scheduled start task since it has finished.
        if table_id in self.start_tasks:
            del self.start_tasks[table_id]

    async def broadcast(self, table_id: str, message: dict) -> None:
        """Broadcasts a message to all connected clients on a table.
        Clients whose send fails are removed from the connection list."""
        if table_id not in self.connections:
            return
        message_text = json.dumps(message)
        closed_players = []
        for player, ws in list(self.connections[table_id].items()):
            try:
                await ws.send_text(message_text)
            except Exception:
                # If sending fails, mark this client to remove.
                closed_players.append(player)
        for player in closed_players:
            self.connections[table_id].pop(player, None)

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
        print(f"[DEBUG] Disconnect called for player '{player_name}' on table {table_id}")
        # Remove the websocket connection.
        if table_id in self.connections:
            self.connections[table_id].pop(player_name, None)

        if table_id in self.tables:
            # Remove the player from both seated and waiting lists.
            if player_name in self.tables[table_id]["players"]:
                self.tables[table_id]["players"].remove(player_name)
            if player_name in self.tables[table_id]["waiting"]:
                self.tables[table_id]["waiting"].remove(player_name)
            print(f"[DEBUG] After disconnect, table {table_id} players: {self.tables[table_id]['players']}")
            await self.broadcast(table_id, {
                "type": "table_update",
                "players": self.tables[table_id]["players"],
                "waiting": self.tables[table_id]["waiting"]
            })

            # If a game start is scheduled but now there are not enough players, cancel the scheduled start.
            if table_id in self.start_tasks and len(self.tables[table_id]["players"]) < MIN_PLAYERS:
                task = self.start_tasks.pop(table_id)
                task.cancel()
                print(f"[DEBUG] Cancelled scheduled game start for table {table_id} due to insufficient players.")
                await self.broadcast(table_id, {
                    "type": "game_cancelled",
                    "message": "Game cancelled due to insufficient players."
                })

            # If an active game is in progress but the number of players has dropped below the minimum,
            # terminate the game and inform the remaining players.
            if table_id in self.active_games and len(self.tables[table_id]["players"]) < MIN_PLAYERS:
                del self.active_games[table_id]
                print(f"[DEBUG] Active game on table {table_id} cancelled due to insufficient players.")
                await self.broadcast(table_id, {
                    "type": "game_cancelled",
                    "message": "Game cancelled due to insufficient players."
                })


server = PokerServer()

app = FastAPI()

@app.websocket("/ws/{player_name}")
async def websocket_endpoint(websocket: WebSocket, player_name: str):
    param_table_id = websocket.query_params.get("table_id")
    table_id = param_table_id if param_table_id else server.get_available_table()

    await server.connect(table_id, player_name, websocket)
    await server.join_table(table_id, player_name)

    try:
        while True:
            data = await websocket.receive_text()
            message = json.loads(data)
            await server.handle_action(
                table_id, player_name, message["action"], message.get("amount", 0)
            )
    except Exception:
        # This includes WebSocketDisconnect and any other exception.
        await server.disconnect(table_id, player_name)
