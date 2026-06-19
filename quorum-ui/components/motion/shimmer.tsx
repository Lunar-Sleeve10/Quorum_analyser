"use client"

import { AnimatePresence, motion } from "motion/react"
import { useEffect, useState } from "react"
import { motionConfig } from "@/lib/motion-config"
import { cn } from "@/lib/utils"

/* ------------------------------------------------------------------ */
/* ShimmerBlock — shimmering placeholder skeleton                      */
/* ------------------------------------------------------------------ */

interface ShimmerBlockProps {
  /** Width (CSS value, default "100%"). */
  width?: string
  /** Height (CSS value, default "1rem"). */
  height?: string
  /** Additional CSS classes. */
  className?: string
  /** Border radius class (default "rounded-md"). */
  rounded?: string
}

/**
 * A shimmering placeholder block that replaces static "Loading…" text.
 * The shimmer sweep is a pure CSS animation (see globals.css).
 */
export function ShimmerBlock({
  width = "100%",
  height = "1rem",
  className,
  rounded = "rounded-md",
}: ShimmerBlockProps) {
  const base = cn(rounded, "bg-muted", className)

  if (!motionConfig.shimmerLoading) {
    return <div className={base} style={{ width, height }} />
  }

  return <div className={cn(base, "shimmer-block")} style={{ width, height }} />
}

/**
 * A group of shimmer blocks that mimic a loading card layout.
 */
export function ShimmerCard({ className }: { className?: string }) {
  return (
    <div className={cn("space-y-3 rounded-xl border border-border p-4", className)}>
      <ShimmerBlock width="40%" height="0.75rem" />
      <ShimmerBlock width="100%" height="2rem" />
      <ShimmerBlock width="70%" height="0.75rem" />
    </div>
  )
}

/* ------------------------------------------------------------------ */
/* CyclingText — animated status text that rotates through phrases     */
/* ------------------------------------------------------------------ */

const DEFAULT_PHRASES = [
  "Routing your question…",
  "Agents collaborating…",
  "Analyzing data…",
  "Building report…",
]

interface CyclingTextProps {
  /** Phrases to cycle through. */
  phrases?: string[]
  /** Milliseconds between phrase changes (default 2500). */
  interval?: number
  /** Additional CSS classes. */
  className?: string
}

/**
 * Displays a series of status phrases that cycle with a smooth fade transition.
 * Uses Motion's AnimatePresence for enter/exit animations.
 */
export function CyclingText({
  phrases = DEFAULT_PHRASES,
  interval = 2500,
  className,
}: CyclingTextProps) {
  const [index, setIndex] = useState(0)

  useEffect(() => {
    if (!motionConfig.shimmerLoading) return
    const id = setInterval(() => {
      setIndex((prev) => (prev + 1) % phrases.length)
    }, interval)
    return () => clearInterval(id)
  }, [phrases.length, interval])

  if (!motionConfig.shimmerLoading) {
    return <span className={className}>{phrases[0]}</span>
  }

  return (
    <span className={cn("relative inline-flex items-center", className)} style={{ minHeight: "1.25em" }}>
      <AnimatePresence mode="wait">
        <motion.span
          key={index}
          initial={{ opacity: 0, y: 8, filter: "blur(4px)" }}
          animate={{ opacity: 1, y: 0, filter: "blur(0px)" }}
          exit={{ opacity: 0, y: -8, filter: "blur(4px)" }}
          transition={{ duration: 0.35, ease: "easeInOut" }}
          className="inline-block"
        >
          {phrases[index]}
        </motion.span>
      </AnimatePresence>
    </span>
  )
}
