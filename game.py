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
    
    def __repr__(self) -> str:
        return f"{self.name} ({self.chips} chips) - Hand: {self.hand}"

class TexasHoldEm:
    def __init__(self, players: List[str]) -> None:
        self.deck: Deck = Deck()
        self.players: List[Player] = [Player(name) for name in players]
        self.community_cards: List[Card] = []
        self.pot: int = 0
        self.dealer_index: int = 0
    
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
    
    def play_tournament(self, starting_chips: int = 1000) -> None:
        print("Starting tournament...")
        for player in self.players:
            player.chips = starting_chips
        
        while len([p for p in self.players if p.chips > 0]) > 1:
            self.play_hand()
        
        winner: Player = next(p for p in self.players if p.chips > 0)
        print(f"{winner.name} wins the tournament!")

if __name__ == "__main__":
    players: List[str] = ["Alice", "Bob", "Charlie", "Dana"]
    game: TexasHoldEm = TexasHoldEm(players)
    game.play_tournament()
