import random
from collections import Counter

class Card:
    SUITS = ['Hearts', 'Diamonds', 'Clubs', 'Spades']
    RANKS = ['2', '3', '4', '5', '6', '7', '8', '9', '10', 'J', 'Q', 'K', 'A']
    RANK_VALUES = {rank: i for i, rank in enumerate(RANKS, start=2)}
    
    def __init__(self, rank, suit):
        self.rank = rank
        self.suit = suit
    
    def __repr__(self):
        return f"{self.rank} of {self.suit}"

class Deck:
    def __init__(self):
        self.cards = [Card(rank, suit) for suit in Card.SUITS for rank in Card.RANKS]
        random.shuffle(self.cards)
    
    def draw(self, num=1):
        return [self.cards.pop() for _ in range(num)] if len(self.cards) >= num else None

class Player:
    def __init__(self, name, chips=1000):
        self.name = name
        self.chips = chips
        self.hand = []
        self.active = True
        self.current_bet = 0
    
    def __repr__(self):
        return f"{self.name} ({self.chips} chips) - Hand: {self.hand}"

class TexasHoldEm:
    def __init__(self, players):
        self.deck = Deck()
        self.players = [Player(name) for name in players]
        self.community_cards = []
        self.pot = 0
        self.dealer_index = 0
    
    def deal_hands(self):
        print("Dealing hands...")
        for player in self.players:
            player.hand = self.deck.draw(2)
            print(f"{player.name} receives: {player.hand}")
    
    def deal_community_cards(self, num):
        cards = self.deck.draw(num)
        self.community_cards.extend(cards)
        print(f"Dealing {num} community card(s): {cards}")
    
    def post_blinds(self, small_blind=10, big_blind=20):
        small_blind_player = self.players[(self.dealer_index + 1) % len(self.players)]
        big_blind_player = self.players[(self.dealer_index + 2) % len(self.players)]
        
        small_blind_player.chips -= small_blind
        big_blind_player.chips -= big_blind
        
        small_blind_player.current_bet = small_blind
        big_blind_player.current_bet = big_blind
        
        self.pot += small_blind + big_blind
        print(f"{small_blind_player.name} posts small blind ({small_blind} chips).")
        print(f"{big_blind_player.name} posts big blind ({big_blind} chips).")
    
    def betting_round(self):
        print("Starting betting round...")
        highest_bet = max(player.current_bet for player in self.players)
        active_players = [p for p in self.players if p.chips > 0]
        
        for player in active_players:
            if player.current_bet < highest_bet:
                call_amount = highest_bet - player.current_bet
                player.chips -= call_amount
                player.current_bet += call_amount
                self.pot += call_amount
                print(f"{player.name} calls with {call_amount} chips.")
    

    def evaluate_hand(self, player):
        all_cards = sorted(player.hand + self.community_cards, key=lambda card: Card.RANK_VALUES[card.rank], reverse=True)
        rank_counts = Counter(Card.RANK_VALUES[card.rank] for card in all_cards)
        sorted_counts = sorted(rank_counts.items(), key=lambda x: (-x[1], -x[0]))
        suits = Counter(card.suit for card in all_cards)
        flush = max(suits.values()) >= 5
        ranks = sorted(set(rank_counts.keys()), reverse=True)
        straight = any(ranks[i] - ranks[i+4] == 4 for i in range(len(ranks) - 4)) or ranks[:5] == [14, 5, 4, 3, 2]
        
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
    
    def determine_winners(self):
        best_hand = max(self.players, key=self.evaluate_hand)
        best_score = self.evaluate_hand(best_hand)
        winners = [p for p in self.players if self.evaluate_hand(p) == best_score]
        split_pot = self.pot // len(winners)
        for winner in winners:
            winner.chips += split_pot
        if len(winners) == 1:
            print(winners[0].name, "won the pot of", self.pot, "chips.")
        else:
            print(f"Winners: {', '.join(p.name for p in winners)} split the pot of {self.pot} chips.")
    
    def play_hand(self):
        print("\nStarting a new hand...")
        self.deck = Deck()
        self.community_cards = []
        self.pot = 0
        for player in self.players:
            player.current_bet = 0
        
        self.deal_hands()
        self.post_blinds()
        self.betting_round()
        
        for num in [3, 1, 1]:
            self.deal_community_cards(num)
            self.betting_round()
        
        self.determine_winners()
        self.dealer_index = (self.dealer_index + 1) % len(self.players)
    
    def play_tournament(self, starting_chips=1000):
        print("Starting tournament...")
        for player in self.players:
            player.chips = starting_chips
        
        while len([p for p in self.players if p.chips > 0]) > 1:
            self.play_hand()
        
        winner = next(p for p in self.players if p.chips > 0)
        print(f"{winner.name} wins the tournament!")

if __name__ == "__main__":
    players = ["Alice", "Bob", "Charlie", "Dana"]
    game = TexasHoldEm(players)
    game.play_tournament()
