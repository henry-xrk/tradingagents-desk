import { useEffect, useId, useRef, type ReactNode, type RefObject } from "react";

export function Dialog({
  open,
  title,
  onClose,
  returnFocus,
  children,
}: {
  open: boolean;
  title: string;
  onClose: () => void;
  returnFocus?: RefObject<HTMLElement | null>;
  children: ReactNode;
}) {
  const ref = useRef<HTMLDialogElement>(null);
  const titleId = useId();
  useEffect(() => {
    const dialog = ref.current;
    if (!open || !dialog) return;
    dialog.showModal();
    const trigger = returnFocus?.current ?? null;
    return () => {
      trigger?.focus();
    };
  }, [open, returnFocus]);
  if (!open) return null;
  return (
    <dialog
      ref={ref}
      aria-labelledby={titleId}
      className="max-h-[min(100%-2rem,40rem)] w-[min(100%-2rem,36rem)] overflow-hidden rounded-md border border-line bg-paper p-0 text-ink shadow-none"
      onClose={onClose}
    >
      <div className="border-b border-line px-4 py-3">
        <h2 id={titleId} className="text-sm font-medium">{title}</h2>
      </div>
      <div className="max-h-[calc(min(100vh-2rem,40rem)-3rem)] overflow-y-auto px-4 py-3">{children}</div>
    </dialog>
  );
}
