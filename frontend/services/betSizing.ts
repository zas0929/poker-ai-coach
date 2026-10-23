export interface BetPreset { label: string; value: number; allIn: boolean }
interface SizingInput {
  action: 'bet' | 'raise'; pot: number; highestBet: number; callAmount: number;
  minimum: number; maximum: number; stack: number; currentBet: number;
  recommended?: number | null;
}

export function betSizing(input: SizingInput) {
  const { action, pot, highestBet, callAmount, minimum, maximum, stack, currentBet, recommended } = input;
  if (!Number.isInteger(minimum) || !Number.isInteger(maximum) || minimum < 1 || maximum < minimum) {
    return { presets: [] as BetPreset[], defaultAmount: 0, stackLimited: false };
  }
  const raw = action === 'raise' ? [
    { label: 'x2', value: highestBet * 2 }, { label: 'x3', value: highestBet * 3 },
    { label: 'Pot', value: highestBet + pot + callAmount },
  ] : [
    { label: '1/2 pot', value: Math.round(pot / 2) },
    { label: '2/3 pot', value: Math.round(pot * 2 / 3) }, { label: 'Pot', value: pot },
  ];
  const allInTotal = stack + currentBet;
  const presets: BetPreset[] = [];
  for (const preset of raw) {
    const value = Math.min(maximum, Math.max(minimum, preset.value));
    if (presets.some(item => item.value === value)) continue;
    const allIn = value === allInTotal;
    const label = allIn ? action === 'raise' ? 'All-in to' : 'All in' : preset.value > maximum ? 'Max.' : preset.value < minimum ? 'Min.' : preset.label;
    presets.push({ label, value, allIn });
  }
  // When every pot fraction is too large, expose the ordinary minimum as well.
  if (minimum < maximum && presets.every(preset => preset.value === maximum)) {
    presets.unshift({ label: 'Min.', value: minimum, allIn: minimum === allInTotal });
  }
  const hasRecommendation = recommended != null && Number.isInteger(recommended) && recommended >= minimum && recommended <= maximum;
  const target = action === 'raise' ? highestBet * 2 : Math.round(pot / 2);
  // Opening the editor must not silently select all-in just because a preset exceeds the stack.
  const defaultAmount = hasRecommendation ? recommended : target >= maximum && minimum < maximum ? minimum : Math.min(maximum, Math.max(minimum, target));
  return { presets, defaultAmount, stackLimited: maximum === allInTotal && minimum < maximum && raw.some(preset => preset.value > maximum) };
}
