import { Component, type ReactNode } from "react";

interface Props {
  children: ReactNode;
}

interface State {
  failed: boolean;
}

/** Last-ditch guard: a render error shows a reload prompt instead of a white screen. */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { failed: false };

  static getDerivedStateFromError(): State {
    return { failed: true };
  }

  componentDidCatch(error: Error): void {
    console.error("render failure", error);
  }

  render() {
    if (this.state.failed) {
      return (
        <p className="splash">
          Something broke while drawing this screen.
          <button onClick={() => window.location.reload()}>Reload</button>
        </p>
      );
    }
    return this.props.children;
  }
}
