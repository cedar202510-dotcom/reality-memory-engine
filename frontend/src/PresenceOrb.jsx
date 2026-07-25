const rippleDelays = ["0s", "2.5s"];

export default function PresenceOrb({ state = "idle" }) {
  return (
    <div className={`presence-orb presence-orb--${state}`} aria-hidden="true">
      {rippleDelays.map((delay) => (
        <span
          key={delay}
          className="presence-orb__ripple"
          style={{ "--ripple-delay": delay }}
        />
      ))}
      <div className="presence-orb__core">
        <span />
      </div>
    </div>
  );
}
