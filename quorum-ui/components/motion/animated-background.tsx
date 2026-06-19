"use client"

import { motionConfig } from "@/lib/motion-config"

/**
 * Floating gradient blobs for a modern SaaS hero backdrop.
 * Uses pure CSS keyframe animations — zero JS per frame, fully GPU-composited.
 * Place inside a `position: relative` container; renders as an absolutely
 * positioned overlay with `pointer-events: none`.
 */
export function AnimatedBackground() {
  if (!motionConfig.animatedBackground) return null

  return (
    <div
      aria-hidden
      className="pointer-events-none absolute inset-0 -z-10 overflow-hidden"
    >
      {/* Indigo-violet blob */}
      <div className="animated-blob animated-blob-1" />
      {/* Teal-cyan blob */}
      <div className="animated-blob animated-blob-2" />
      {/* Fuchsia-rose blob */}
      <div className="animated-blob animated-blob-3" />
      {/* Amber accent blob */}
      <div className="animated-blob animated-blob-4" />
    </div>
  )
}
