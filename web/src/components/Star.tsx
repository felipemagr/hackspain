/** Favorite mark. Ink, never a state color. */
export function Star({ filled }: { filled: boolean }) {
  return (
    <svg className={`star ${filled ? "is-filled" : ""}`} width="14" height="14" viewBox="0 0 24 24" aria-hidden>
      <path d="M12 3.5l2.6 5.3 5.9.9-4.2 4.1 1 5.8L12 16.9l-5.3 2.7 1-5.8-4.2-4.1 5.9-.9z" />
    </svg>
  );
}
