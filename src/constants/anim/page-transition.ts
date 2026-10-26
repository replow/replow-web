import type { TransitionAnimationPair, TransitionDirectionalAnimations } from 'astro';
import { animation } from '../design-tokens';

/**
 * Root cross-fade. Astro's fade keyframes blend with plus-lighter, which keeps the picture steady only
 * while the two opacities add up to one, so both halves share one duration and curve: any offset
 * brightens the page where they overlap and dips it where neither is opaque. The curve and length
 * keep the two snapshots synchronized throughout the longer page transition.
 */
const crossFade: TransitionAnimationPair = {
  old: { name: 'astroFadeOut', duration: '680ms', easing: animation.easing['out-quart'], fillMode: 'both' },
  new: { name: 'astroFadeIn', duration: '680ms', easing: animation.easing['out-quart'], fillMode: 'both' },
};

export const pageTransition: TransitionDirectionalAnimations = {
  forwards: crossFade,
  backwards: crossFade,
};
