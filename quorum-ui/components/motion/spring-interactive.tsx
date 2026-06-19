"use client"

import { motion } from "motion/react"
import type { ReactNode } from "react"
import { motionConfig } from "@/lib/motion-config"

interface SpringInteractiveProps {
  children: ReactNode
  /** Extra CSS classes forwarded to the wrapper. */
  className?: string
  /** Disable the effect for this instance even when globally enabled. */
  disabled?: boolean
  /** Scale factor on hover (default 1.02). */
  hoverScale?: number
  /** Scale factor on tap/press (default 0.97). */
  tapScale?: number
  /** Enable subtle rotation on hover (default true). */
  rotate?: boolean
  /** Enable glow box-shadow on hover (default false). */
  glow?: boolean
  /** Render as inline element instead of block. */
  inline?: boolean
}

/**
 * Wraps any interactive element with springy hover and tap micro-interactions.
 * Uses GPU-accelerated transforms only (scale, rotate).
 * Renders children unchanged when disabled or feature flag is off.
 */
export function SpringInteractive({
  children,
  className,
  disabled = false,
  hoverScale = 1.02,
  tapScale = 0.97,
  rotate = true,
  glow = false,
  inline = false,
}: SpringInteractiveProps) {
  if (!motionConfig.microInteractions || disabled) {
    return <>{children}</>
  }

  return (
    <motion.div
      className={className}
      style={{
        display: inline ? "inline-block" : undefined,
        willChange: "transform",
      }}
      whileHover={{
        scale: hoverScale,
        rotate: rotate ? 0.5 : 0,
        boxShadow: glow
          ? "0 0 20px rgba(99, 102, 241, 0.15), 0 0 60px rgba(99, 102, 241, 0.05)"
          : undefined,
      }}
      whileTap={{ scale: tapScale }}
      transition={{
        type: "spring",
        stiffness: 400,
        damping: 25,
        mass: 0.8,
      }}
    >
      {children}
    </motion.div>
  )
}
