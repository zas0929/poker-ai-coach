// Quiet, short physical textures. No external recordings or network requests.
export function tableAudioSamples(kind: 'deal' | 'reveal' | 'chips' | 'win', sampleRate: number, variation = 0) {
  const card = kind === 'deal' || kind === 'reveal';
  const duration = card ? .115 : .085;
  const samples = new Float32Array(Math.ceil(sampleRate * duration));
  let low = 0, slow = 0;
  const cutoff = card ? 1150 : 2200;
  const alpha = 1 - Math.exp(-2 * Math.PI * cutoff / sampleRate);
  const slowAlpha = 1 - Math.exp(-2 * Math.PI * 160 / sampleRate);
  const pitch = 1 + (variation % 5 - 2) * .025;
  for (let i = 0; i < samples.length; i++) {
    const time = i / sampleRate;
    low += alpha * (Math.random() * 2 - 1 - low);
    slow += slowAlpha * (low - slow);
    if (card) {
      // Rounded paper brush: no abrupt attack and no piercing high frequencies.
      const envelope = Math.sin(Math.PI * time / duration) ** 2;
      samples[i] = (low - slow) * envelope * .21;
    } else {
      // Brief, heavily damped clay/plastic contacts, rather than a sustained rattle.
      const attack = 1 - Math.exp(-time / .0025);
      const body = .13 * Math.sin(2 * Math.PI * 1020 * pitch * time) * Math.exp(-time / .013)
        + .075 * Math.sin(2 * Math.PI * 1670 * pitch * time) * Math.exp(-time / .009)
        + .035 * Math.sin(2 * Math.PI * 2410 * pitch * time) * Math.exp(-time / .006);
      const contact = (low - slow) * .08 * Math.exp(-time / .008);
      const fade = Math.min(1, (duration - time) / .012);
      samples[i] = (body + contact) * attack * fade;
    }
  }
  return samples;
}
