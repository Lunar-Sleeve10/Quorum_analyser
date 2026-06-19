/**
 * Central feature flags for UI animations.
 * Toggle any flag to `false` to disable that feature globally —
 * wrapper components will render children unchanged (zero overhead).
 */
export const motionConfig = {
  /** Springy hover/tap scale effects on buttons, cards, and interactive elements. */
  microInteractions: true,

  /** Fade + upward-slide entrance when sections scroll into the viewport. */
  scrollReveal: true,

  /** Floating gradient blobs on the dashboard hero section. */
  animatedBackground: true,

  /** Shimmer placeholders and cycling status text for loading states. */
  shimmerLoading: true,
} as const
