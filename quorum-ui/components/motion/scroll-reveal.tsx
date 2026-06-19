"use client"

import { motion } from "motion/react"
import type { ReactNode } from "react"
import { motionConfig } from "@/lib/motion-config"

interface ScrollRevealProps {
  children: ReactNode
  /** Extra CSS classes. */
  className?: string
  /** Stagger delay in seconds (default 0). */
  delay?: number
  /** Vertical offset in pixels (default 24). */
  y?: number
  /** Duration in seconds (default 0.5). */
  duration?: number
  /** Animate every time the element enters viewport, not just once. */
  repeat?: boolean
  /** Horizontal offset in pixels (default 0). */
  x?: number
  /** Amount of element that must be visible to trigger (default 0.15). */
  amount?: number
}

/**
 * Fade + slide entrance animation triggered when the element scrolls into view.
 * Uses `once: true` by default so each element animates only on first entry.
 * GPU-accelerated: only opacity and transform are animated.
 */
export function ScrollReveal({
  children,
  className,
  delay = 0,
  y = 24,
  x = 0,
  duration = 0.5,
  repeat = false,
  amount = 0.15,
}: ScrollRevealProps) {
  if (!motionConfig.scrollReveal) {
    return <div className={className}>{children}</div>
  }

  return (
    <motion.div
      className={className}
      initial={{ opacity: 0, y, x }}
      whileInView={{ opacity: 1, y: 0, x: 0 }}
      viewport={{ once: !repeat, amount }}
      transition={{
        duration,
        delay,
        ease: [0.25, 0.46, 0.45, 0.94],
      }}
    >
      {children}
    </motion.div>
  )
}

/**
 * Convenience: stagger a list of children with incremental delays.
 */
export function ScrollRevealGroup({
  children,
  className,
  stagger = 0.08,
  y = 24,
}: {
  children: ReactNode[]
  className?: string
  stagger?: number
  y?: number
}) {
  if (!motionConfig.scrollReveal) {
    return <div className={className}>{children}</div>
  }

  return (
    <div className={className}>
      {(Array.isArray(children) ? children : [children]).map((child, i) => (
        <ScrollReveal key={i} delay={i * stagger} y={y}>
          {child}
        </ScrollReveal>
      ))}
    </div>
  )
}
