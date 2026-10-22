/** OneDrive transfer checksum; this is not a cryptographic signature. */
export function quickXorHash(buffer: ArrayBuffer): string {
  const folded = new Uint8Array(160);
  const bytes = new Uint8Array(buffer);
  let slot = 0;
  for (const value of bytes) {
    folded[slot] ^= value;
    slot++;
    if (slot === 160) slot = 0;
  }
  const result = new Uint8Array(20);
  for (let index = 0; index < 160; index++) {
    const bit = (index * 11) % 160;
    const byte = Math.floor(bit / 8);
    const shift = bit % 8;
    result[byte] ^= (folded[index] << shift) & 255;
    if (shift) result[(byte + 1) % 20] ^= folded[index] >>> (8 - shift);
  }
  for (let index = 0; index < 8; index++) {
    result[12 + index] ^= Math.floor(bytes.length / 2 ** (index * 8)) & 255;
  }
  return btoa(String.fromCharCode(...result));
}
