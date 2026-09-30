import { useLayoutEffect, useRef, type ReactNode } from "react";

export function Modal({
  label,
  children,
  onDismiss,
  dismissible = true,
  className = "",
  returnFocus,
}: {
  label: string;
  children: ReactNode;
  onDismiss: () => void;
  dismissible?: boolean;
  className?: string;
  returnFocus?: HTMLElement | null;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  useLayoutEffect(() => {
    const element = dialog.current!;
    const previous = returnFocus || document.activeElement;
    element.showModal();
    return () => {
      element.close();
      queueMicrotask(() => {
        if (
          previous instanceof HTMLElement &&
          previous.isConnected &&
          !document.querySelector("dialog[open]")
        ) {
          previous.focus({ preventScroll: true });
        }
      });
    };
  }, []);
  return (
    <dialog
      ref={dialog}
      className={`modal ${className}`}
      aria-label={label}
      onCancel={(event) => {
        event.preventDefault();
        if (dismissible) onDismiss();
      }}
    >
      {children}
    </dialog>
  );
}
