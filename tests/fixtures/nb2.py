"""Deterministic NB2 controller using the real parser and tracked transport."""
from unittest.mock import MagicMock
from helpers.arduino import Arduino


class NB2Controller(Arduino):
    def __init__(self, v2=False):
        super().__init__()
        self.protocol_v2 = v2
        self._running = self.connected = True
        self.serial_com = MagicMock(is_open=True)
        self.firmware_driver = "DRX-HX711-NB2"
        self.commands = []
        self.hook = None
        self.a_zero, self.b_zero = 0, 1900
        self.factor = 1.0
        self.baseline_valid = True

    def send_tracked(self, command):
        handle = super().send_tracked(command)
        if handle is None:
            return None
        self.commands.append(command)
        self._last_tx = 0
        self._service_tx_queue()
        replies = self.replies(command)
        if self.hook is not None:
            replies = self.hook(command, replies)
        for reply in replies:
            if reply in ("DONE", "OK", "BUSY") and self.protocol_v2:
                reply += "|" + str(handle.sequence)
            self.handle_com(reply)
        return handle

    def replies(self, command):
        if command == "Y":
            return ["Ready to Go", "FIRMWARE|test|DRX-HX711-NB2"]
        if command == "T":
            return ["OK", "FIRMWARE|test|DRX-HX711-NB2"]
        if command.startswith("L5|"):
            _, a, b = command.split("|")
            self.a_zero, self.b_zero = int(a), int(b)
            return [f"ZEROS|{a}|{b}", "DONE"]
        if command.startswith("L0"):
            self.factor = float(command[2:])
            return [f"CALIBRATION|SET|{self.factor}", "DONE"]
        if command == "L1|BASELINE":
            return ["CALIBRATION|TARE|STARTED",
                    f"CALIBRATION|TARE|OK|123|{self.factor}", "DONE"]
        if command.startswith("P"):
            target = command[1:].split("|")[0]
            return [f"MOTION_DONE|P|{target}|{target}", "DONE"]
        if command.startswith("K"):
            target = command[1:]
            return [f"MOTION_DONE|K|{target}|{target}", "DONE"]
        if command.startswith("I"):
            target = max(self.a_zero, int(command[3:])) if command[1:3] == "12" else int(command[3:])
            return [f"MOTION_DONE|I|{target}|{target}", "DONE"]
        if command.startswith("V"):
            return ["SPEED|" + command[1:].replace(",", "|"), "OK"]
        return ["DONE"]
