import React from "react";
import { motion } from "framer-motion";

export default function PresenceOrb({ state }) {
  // state: "idle" | "listening" | "thinking"

  // Base colors for different states
  const colors = {
    idle: ["#56eb8e", "#4eb2cc"], // Green to Aqua
    listening: ["#4eb2cc", "#6e56cf"], // Aqua to Purple
    thinking: ["#da924b", "#e05b5b"] // Warm Orange to Red
  };

  const currentColors = colors[state] || colors.idle;

  return (
    <div style={{ position: "relative", width: 120, height: 120, display: "flex", justifyContent: "center", alignItems: "center" }}>
      {/* Outer Glow / Pulse */}
      <motion.div
        animate={{
          scale: state === "listening" ? [1, 1.5, 1] : state === "thinking" ? [1, 1.2, 1] : 1,
          opacity: state === "listening" ? [0.3, 0.6, 0.3] : state === "thinking" ? [0.2, 0.4, 0.2] : 0.1,
        }}
        transition={{
          duration: state === "listening" ? 1.5 : 2,
          repeat: Infinity,
          ease: "easeInOut"
        }}
        style={{
          position: "absolute",
          width: "100%",
          height: "100%",
          borderRadius: "50%",
          background: `radial-gradient(circle, ${currentColors[0]} 0%, transparent 70%)`,
          filter: "blur(20px)"
        }}
      />
      
      {/* Middle Ring */}
      <motion.div
        animate={{
          rotate: state === "thinking" ? 360 : 0,
          scale: state === "listening" ? [1, 1.1, 1] : 1,
        }}
        transition={{
          rotate: { duration: 3, repeat: Infinity, ease: "linear" },
          scale: { duration: 1.5, repeat: Infinity, ease: "easeInOut" }
        }}
        style={{
          position: "absolute",
          width: "70%",
          height: "70%",
          borderRadius: "50%",
          border: `2px solid ${currentColors[1]}`,
          opacity: 0.5,
          borderStyle: "dashed"
        }}
      />

      {/* Core Orb */}
      <motion.div
        animate={{
          scale: state === "listening" ? [0.9, 1.1, 0.9] : 1,
          boxShadow: `0 0 20px ${currentColors[0]}, inset 0 0 20px ${currentColors[1]}`
        }}
        transition={{
          duration: state === "listening" ? 1 : 2,
          repeat: Infinity,
          ease: "easeInOut"
        }}
        style={{
          width: "40%",
          height: "40%",
          borderRadius: "50%",
          background: `linear-gradient(135deg, ${currentColors[0]}, ${currentColors[1]})`,
          zIndex: 10
        }}
      />
    </div>
  );
}
