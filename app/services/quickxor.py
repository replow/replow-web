"""OneDrive QuickXorHash for transfer integrity (not a cryptographic signature).
Algorithm: Microsoft OneDrive QuickXorHash code snippet.
"""
import base64


class QuickXor:
    def __init__(self):
        self.folded = bytearray(160)
        self.length = 0

    def update(self, data):
        slot = self.length % 160
        for value in data:
            self.folded[slot] ^= value
            slot += 1
            if slot == 160:
                slot = 0
        self.length += len(data)

    def base64(self):
        result = bytearray(20)
        for index, value in enumerate(self.folded):
            bit = (index * 11) % 160
            byte, shift = divmod(bit, 8)
            result[byte] ^= (value << shift) & 255
            if shift:
                result[(byte + 1) % 20] ^= value >> (8 - shift)
        for index in range(8):
            result[12 + index] ^= (self.length >> (8 * index)) & 255
        return base64.b64encode(result).decode()
