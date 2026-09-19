import { useEffect, useRef, useState, type ReactNode } from "react";

interface MenuProps {
  label: ReactNode;
  ariaLabel?: string;
  align?: "left" | "right";
  children: ReactNode;
}

/** A bordered button that opens a panel of checkable options. Closes on Escape or a click outside. */
export function Menu({ label, ariaLabel, align = "left", children }: MenuProps) {
  const [open, setOpen] = useState(false);
  const root = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!open) return;
    const onDown = (e: PointerEvent) => {
      if (!root.current?.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    window.addEventListener("pointerdown", onDown);
    window.addEventListener("keydown", onKey);
    return () => {
      window.removeEventListener("pointerdown", onDown);
      window.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div className="menu" ref={root}>
      <button
        className="menu__button"
        aria-haspopup="true"
        aria-expanded={open}
        aria-label={ariaLabel}
        onClick={() => setOpen((o) => !o)}
      >
        {label}
      </button>
      {open && <div className={`menu__panel menu__panel--${align}`}>{children}</div>}
    </div>
  );
}

interface CheckProps {
  checked: boolean;
  disabled?: boolean;
  onChange: () => void;
  children: ReactNode;
}

export function Check({ checked, disabled, onChange, children }: CheckProps) {
  return (
    <label className={`check ${disabled ? "is-disabled" : ""}`}>
      <input type="checkbox" checked={checked} disabled={disabled} onChange={onChange} />
      <span className="check__box" aria-hidden>
        <svg width="10" height="8" viewBox="0 0 10 8">
          <path d="M1 4 L3.8 6.8 L9 1.2" />
        </svg>
      </span>
      <span className="check__label">{children}</span>
    </label>
  );
}
