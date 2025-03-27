import random
from collections import Counter
from typing import List, Optional, Tuple


class Card:
    SUITS: List[str] = ['Hearts', 'Diamonds', 'Clubs', 'Spades']
    RANKS: List[str] = ['2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K', 'A']
    RANK_VALUES: dict[str, int] = {rank: i for i, rank in enumerate(RANKS, start=2)}

    def __init__(self, rank: str, suit: str) -> None:
        self.rank: str = rank
        self.suit: str = suit

    def __repr__(self) -> str:
        return f"{self.rank} of {self.suit}"


class Deck:
    def __init__(self) -> None:
        self.cards: List[Card] = [Card(rank, suit) for suit in Card.SUITS for rank in Card.RANKS]
        random.shuffle(self.cards)

    def draw(self, num: int = 1) -> Optional[List[Card]]:
        return [self.cards.pop() for _ in range(num)] if len(self.cards) >= num else None


class Player:
    def __init__(self, name: str, chips: int = 1000) -> None:
        self.name: str = name
        self.chips: int = chips
        self.hand: List[Card] = []
        self.active: bool = True
        self.current_bet: int = 0
        self.total_contribution: int = 0  # Added to track total contribution in the hand

    def __repr__(self) -> str:
        # For debugging, __repr__ reveals the hand.
        return f"{self.name} ({self.chips} chips) - Hand: {self.hand}"

    def public_view(self) -> dict:
        """
        Returns a public view of the player that does not include the private hand.
        """
        return {
            "name": self.name,
            "chips": self.chips,
            "current_bet": self.current_bet,
            "active": self.active
        }


class TexasHoldEm:
    def __init__(self, players: List[str]) -> None:
        self.deck: Deck = Deck()
        self.players: List[Player] = [Player(name) for name in players]
        self.community_cards: List[Card] = []
        self.pot: int = 0
        self.dealer_index: int = 0
        # New attributes for game state management:
        self.phase: str = "pre-flop"  # phases: pre-flop, flop, turn, river, showdown
        self.current_turn_index: int = 0
        self.current_bet: int = 0  # highest bet in current betting round

    def start_game(self) -> None:
        # Deal private hands to each player and post blinds.
        print("Starting game: Dealing hands and posting blinds.")
        for player in self.players:
            player.hand = self.deck.draw(2)  # Deal two cards to each player.
            print(f"{player.name} receives: {player.hand}")
        self.post_blinds()
        # Initialize the current bet from the big blind.
        big_blind_player = self.players[(self.dealer_index + 2) % len(self.players)]
        self.current_bet = big_blind_player.current_bet
        # Set turn order: typically the player left of the big blind.
        if len(self.players) == 2:
            self.current_turn_index = self.dealer_index
        else:
            self.current_turn_index = (self.dealer_index + 3) % len(self.players)
        print(f"Betting phase: {self.phase}, starting turn: {self.players[self.current_turn_index].name}")

    def take_action(self, player_name: str, action: str, amount: int = 0) -> Tuple[bool, str]:
        """
        Processes an action (e.g., bet or fold) from the given player if it is their turn.
        Returns a tuple (success, message).
        """
        current_player = self.players[self.current_turn_index]
        if current_player.name != player_name:
            return (False, "It's not your turn.")

        msg = ""
        if action == "fold":
            current_player.active = False
            msg = f"{player_name} folds."
        elif action == "bet":
            # Determine required call amount.
            required_call = self.current_bet - current_player.current_bet
            # Allow going all-in even if the amount is less than the required call.
            if amount < required_call and amount != current_player.chips:
                return (False, f"Minimum required bet is {required_call} chips to call, unless going all-in.")
            if amount > current_player.chips:
                return (False, "Insufficient chips for that bet.")
            current_player.chips -= amount
            current_player.current_bet += amount
            current_player.total_contribution += amount
            self.pot += amount
            # If raised above the current bet, update the betting target.
            if current_player.current_bet > self.current_bet:
                self.current_bet = current_player.current_bet
            msg = f"{player_name} bets {amount} chips."
        else:
            return (False, "Invalid action.")

        print(msg)
        # If only one player remains active, end immediately.
        active_players = [p for p in self.players if p.active]
        if len(active_players) == 1:
            winner = active_players[0]
            self.split_pots()  # Split the pots among eligible players.
            msg += f" Only {winner.name} remains. Remaining pot(s) have been split."
            self.phase = "showdown"
            return (True, msg)

        # Advance to the next active player.
        self.next_turn()

        # If all remaining players have matched bets, end the betting round.
        if self.is_betting_round_complete():
            msg += " Betting round complete."
            self.advance_phase()
            msg += f" Advancing phase to {self.phase}."
            # Reset bets for next round (except at showdown).
            if self.phase != "showdown":
                for p in self.players:
                    p.current_bet = 0
                self.current_bet = 0
                self.set_next_turn_for_new_betting_round()
            else:
                self.split_pots()
                msg += " Showdown: Pots have been split among winners."
        else:
            msg += f" Next turn: {self.players[self.current_turn_index].name}."
        return (True, msg)

    def next_turn(self) -> None:
        """Advance current_turn_index to the next active player."""
        num_players = len(self.players)
        for i in range(1, num_players+1):
            next_index = (self.current_turn_index + i) % num_players
            if self.players[next_index].active:
                self.current_turn_index = next_index
                return

    def is_betting_round_complete(self) -> bool:
        """Returns True if all active players have put in the same bet this round."""
        active_players = [p for p in self.players if p.active]
        if not active_players:
            return True
        bets = {p.current_bet for p in active_players}
        return len(bets) == 1

    def advance_phase(self) -> None:
        """Moves the game to the next phase and deals community cards as needed."""
        phases = ["pre-flop", "flop", "turn", "river", "showdown"]
        current_index = phases.index(self.phase)
        if current_index < len(phases) - 1:
            self.phase = phases[current_index + 1]
            if self.phase == "flop":
                self.deal_community_cards(3)
            elif self.phase in ["turn", "river"]:
                self.deal_community_cards(1)
            # No dealing for showdown.
        print(f"Advanced to phase: {self.phase}")

    def set_next_turn_for_new_betting_round(self) -> None:
        """
        After a betting round, resets the turn order.
        For example, the player immediately to the left of the dealer starts.
        """
        num_players = len(self.players)
        for i in range(num_players):
            candidate_index = (self.dealer_index + 1 + i) % num_players
            if self.players[candidate_index].active:
                self.current_turn_index = candidate_index
                print(f"New betting round starting with {self.players[candidate_index].name}")
                return

    def determine_winner(self) -> List[Player]:
        """
        Evaluates the active players' hands and returns a list of winner(s).
        Compares the base hand score (index 0) and then the kicker cards (index 1)
        element-wise.
        """
        active_players = [p for p in self.players if p.active]
        if not active_players:
            return []

        winners = []
        best_score = -1
        best_kickers = []

        for p in active_players:
            score, kickers = self.evaluate_hand(p)
            if score > best_score:
                best_score = score
                best_kickers = kickers
                winners = [p]
            elif score == best_score:
                # Compare kicker cards (assumes kickers lists are ordered in descending order)
                if kickers > best_kickers:
                    best_kickers = kickers
                    winners = [p]
                elif kickers == best_kickers:
                    winners.append(p)

        print(f"Determined winner(s): {[p.name for p in winners]} with hand value ({best_score}, {best_kickers})")
        return winners

    def deal_hands(self) -> None:
        print("Dealing hands...")
        for player in self.players:
            player.hand = self.deck.draw(2)  # type: ignore
            print(f"{player.name} receives: {player.hand}")

    def deal_community_cards(self, num: int) -> None:
        cards = self.deck.draw(num)  # type: ignore
        self.community_cards.extend(cards)
        print(f"Dealing {num} community card(s): {cards}")

    def post_blinds(self, small_blind: int = 10, big_blind: int = 20) -> None:
        small_blind_player: Player = self.players[(self.dealer_index + 1) % len(self.players)]
        big_blind_player: Player = self.players[(self.dealer_index + 2) % len(self.players)]

        small_blind_player.chips -= small_blind
        big_blind_player.chips -= big_blind

        small_blind_player.current_bet = small_blind
        big_blind_player.current_bet = big_blind

        small_blind_player.total_contribution = small_blind
        big_blind_player.total_contribution = big_blind

        self.pot += small_blind + big_blind
        print(f"{small_blind_player.name} posts small blind ({small_blind} chips).")
        print(f"{big_blind_player.name} posts big blind ({big_blind} chips).")

    def betting_round(self) -> None:
        print("Starting betting round...")
        highest_bet: int = max(player.current_bet for player in self.players)
        active_players: List[Player] = [p for p in self.players if p.chips > 0]

        for player in active_players:
            if player.current_bet < highest_bet:
                call_amount: int = highest_bet - player.current_bet
                player.chips -= call_amount
                player.current_bet += call_amount
                player.total_contribution += call_amount  # Update total contribution
                self.pot += call_amount
                print(f"{player.name} calls with {call_amount} chips.")

    def evaluate_hand(self, player: Player) -> Tuple[int, List[int]]:
        all_cards: List[Card] = sorted(player.hand + self.community_cards, key=lambda card: Card.RANK_VALUES[card.rank], reverse=True)
        rank_counts = Counter(Card.RANK_VALUES[card.rank] for card in all_cards)
        sorted_counts = sorted(rank_counts.items(), key=lambda x: (-x[1], -x[0]))
        suits = Counter(card.suit for card in all_cards)
        flush: bool = max(suits.values()) >= 5
        ranks: List[int] = sorted(set(rank_counts.keys()), reverse=True)
        straight: bool = any(ranks[i] - ranks[i+4] == 4 for i in range(len(ranks) - 4)) or ranks[:5] == [14, 5, 4, 3, 2]

        if flush and straight:
            return (9, ranks[:5])
        if sorted_counts[0][1] == 4:
            return (8, [sorted_counts[0][0]] + ranks[:1])
        if sorted_counts[0][1] == 3 and sorted_counts[1][1] == 2:
            return (7, [sorted_counts[0][0], sorted_counts[1][0]])
        if flush:
            return (6, ranks[:5])
        if straight:
            return (5, ranks[:5])
        if sorted_counts[0][1] == 3:
            return (4, [sorted_counts[0][0]] + ranks[:2])
        if sorted_counts[0][1] == 2 and sorted_counts[1][1] == 2:
            return (3, [sorted_counts[0][0], sorted_counts[1][0]] + ranks[:1])
        if sorted_counts[0][1] == 2:
            return (2, [sorted_counts[0][0]] + ranks[:3])
        return (1, ranks[:5])

    def split_pots(self) -> None:
        """
        Splits the pot into main and side pots based on each player's total contributions.
        Each pot is then awarded to the best hand among eligible (active) players.
        """
        # Copy each player's total contribution.
        contributions = {p: p.total_contribution for p in self.players}
        pots = []

        # Calculate side pots.
        while True:
            active_contribs = [(p, amt) for p, amt in contributions.items() if amt > 0]
            if not active_contribs:
                break
            min_amt = min(amt for _, amt in active_contribs)
            num_players = len(active_contribs)
            pot_amount = min_amt * num_players
            # Only players who have not folded are eligible for winning this pot.
            eligible_players = [p for p, amt in active_contribs if p.active]
            pots.append({"amount": pot_amount, "eligible": eligible_players})
            # Subtract min_amt from each player's contribution.
            for p, amt in active_contribs:
                contributions[p] -= min_amt

        # Distribute each pot among its winners.
        for pot in pots:
            if pot["eligible"]:
                winners = self.determine_winner(pot["eligible"])
                split_amount = pot["amount"] // len(winners)
                for winner in winners:
                    winner.chips += split_amount
                print(f"Pot of {pot['amount']} chips split among {[w.name for w in winners]} (each receives {split_amount}).")
            else:
                print(f"Pot of {pot['amount']} chips had no eligible players to win.")
        # Reset the main pot.
        self.pot = 0


if __name__ == "__main__":
    players: List[str] = ["Alice", "Bob", "Charlie", "Dana"]
    game: TexasHoldEm = TexasHoldEm(players)
    game.start_game()
