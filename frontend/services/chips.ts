// Display denominations for this virtual-chip table (rooms may use different conventions).
export const CHIP_VALUES = [
  { value: 25000, color: '#d66ba3', ink: '#161c19' },
  { value: 5000, color: '#df802b', ink: '#161c19' },
  { value: 1000, color: '#e7ca43', ink: '#161c19' },
  { value: 500, color: '#8753b8', ink: '#fff' },
  { value: 100, color: '#252b30', ink: '#fff' },
  { value: 25, color: '#248756', ink: '#fff' },
  { value: 5, color: '#bd3544', ink: '#fff' },
  { value: 1, color: '#e9e7db', ink: '#17221b' },
];
export function chipBreakdown(amount: number) {
  let remaining = Math.max(0, Math.floor(amount));
  return CHIP_VALUES.flatMap(chip => {
    const count = Math.floor(remaining / chip.value);
    remaining %= chip.value;
    return count ? [{ ...chip, count }] : [];
  });
}
