import React from "react";
import { motion } from "framer-motion";

export default function PresenceOrb({ state }) {
  // state: "idle" | "listening" | "thinking"

  // Base colors for different states
  const colors = {
    idle: "rgba(86, 235, 142, 0.6)",       // Green
    listening: "rgba(78, 178, 204, 0.6)",  // Aqua
    thinking: "rgba(218, 146, 75, 0.6)"    // Warm Orange
  };

  const coreColors = {
    idle: "#56eb8e",
    listening: "#4eb2cc",
    thinking: "#da924b"
  };

  const color = colors[state] || colors.idle;
  const coreColor = coreColors[state] || coreColors.idle;

  // Determine animation scales and speeds based on state
  const isListening = state === "listening";
  const isThinking = state === "thinking";

  return (
    <div style={{ position: "relative", width: 200, height: 200, display: "flex", justifyContent: "center", alignItems: "center" }}>
      
      {/* Ripple 1 */}
      <motion.div
        animate={{
          scale: isListening ? [1, 8] : [1, 6],
          opacity: isListening ? [0.8, 0] : [0.6, 0]
        }}
        transition={{
          duration: isListening ? 3 : 5,
          repeat: Infinity,
          ease: "easeOut"
        }}
        style={{
          position: "absolute",
          width: 50,
          height: 50,
          borderRadius: "50%",
          background: `radial-gradient(circle, ${color} 0%, transparent 70%)`,
          zIndex: 1
        }}
      />

      {/* Ripple 2 */}
      <motion.div
        animate={{
          scale: isListening ? [1, 8] : [1, 6],
          opacity: isListening ? [0.8, 0] : [0.6, 0]
        }}
        transition={{
          duration: isListening ? 3 : 5,
          repeat: Infinity,
          ease: "easeOut",
          delay: isListening ? 1.5 : 2.5
        }}
        style={{
          position: "absolute",
          width: 50,
          height: 50,
          borderRadius: "50%",
          background: `radial-gradient(circle, ${color} 0%, transparent 70%)`,
          zIndex: 1
        }}
      />

      {/* Hybrid Core */}
      <motion.div
        animate={{
          scale: isThinking ? [1, 1.2, 1] : isListening ? [1, 1.4, 1] : [1, 1.3, 1],
          opacity: isListening ? 1 : 0.8,
          boxShadow: isThinking 
            ? `0 0 40px ${coreColor}, inset 0 0 20px #fff`
            : `0 0 20px ${color}`
        }}
        transition={{
          duration: isListening ? 1.5 : 3,
          repeat: Infinity,
          ease: "easeInOut"
        }}
        style={{
          width: 50,
          height: 50,
          borderRadius: "50%",
          background: `radial-gradient(circle, ${coreColor} 20%, transparent 100%)`,
          zIndex: 10
        }}
      />
    </div>
  );
}
