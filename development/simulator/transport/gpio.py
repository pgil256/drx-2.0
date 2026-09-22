"""Stateful GPIO adapter recording the real application's local outputs."""
from types import ModuleType
from typing import Callable, Dict, Optional


class SimulatedGPIO(ModuleType):
    """Implement the Raspberry Pi calls used by KneeSpa without accessing hardware."""

    HIGH, LOW, OUT, IN, BCM = 1, 0, 1, 0, 11
    PUD_UP, PUD_DOWN, BOTH, RISING, FALLING = 22, 21, 33, 31, 32

    def __init__(self, post: Callable[[str, dict], None]) -> None:
        super().__init__("RPi.GPIO")
        self.post = post
        self.levels: Dict[int, int] = {}
        self.modes: Dict[int, int] = {}

    def setmode(self, mode: int) -> None:
        if mode != self.BCM:
            raise ValueError("Simulator uses BCM pin numbers")

    def setwarnings(self, enabled: bool) -> None:
        pass

    def setup(self, pin: int, mode: int, **kwargs: object) -> None:
        self.modes[pin] = mode
        if "initial" in kwargs:
            self.output(pin, int(kwargs["initial"]))

    def output(self, pin: int, level: int) -> None:
        self.levels[pin] = int(level)
        self.post("gpio", {"pin": pin, "level": int(level)})

    def input(self, pin: int) -> int:
        return self.levels.get(pin, self.HIGH)

    def cleanup(self, pin: Optional[int] = None) -> None:
        for current in list(self.levels) if pin is None else [pin]:
            self.output(current, self.LOW)
        self.modes.clear()
