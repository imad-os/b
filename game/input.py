"""Input adapters. Replace KeyboardInput with a Joy-Con motion adapter later."""


class KeyboardInput:
    def resolve_move(self, event, available_moves):
        if not hasattr(event, "unicode"):
            return None
        key = event.unicode.lower()
        return next((move for move in available_moves if move.key == key), None)
