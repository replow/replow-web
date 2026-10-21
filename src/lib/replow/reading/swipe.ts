/** Handle Touch Events independently from mouse/pen pointers, including iOS WebViews. */
export function bindPageSwipe(
  target: HTMLElement | Document,
  turn: (direction: 'next' | 'prev') => void,
  enabled: () => boolean,
  signal: AbortSignal,
) {
  const doc = target.ownerDocument || (target as Document);
  const surface = target.nodeType === 9 ? doc.documentElement : (target as HTMLElement);
  let start: { id: number; x: number; y: number } | undefined;
  let horizontal = false;
  const pointers = new Set<number>();
  const selected = () => {
    const selection = doc.getSelection();
    return Boolean(selection && !selection.isCollapsed && selection.anchorNode && surface.contains(selection.anchorNode));
  };
  const reset = () => {
    start = undefined;
    horizontal = false;
  };
  const blocked = (element: EventTarget | null) =>
    Boolean((element as Element | null)?.closest?.('a, button, input, select, textarea, [contenteditable="true"]'));
  function begin(id: number, x: number, y: number, element: EventTarget | null) {
    reset();
    if (!enabled() || selected() || blocked(element)) return;
    start = { id, x, y };
  }
  function move(x: number, y: number, event: Event) {
    if (!start) return;
    if (!enabled() || selected()) return reset();
    const dx = Math.abs(x - start.x),
      dy = Math.abs(y - start.y);
    if (!horizontal && dy > 24 && dy > dx * 1.3) return reset();
    if (dx > 8 && dx > dy * 1.2) horizontal = true;
    if (horizontal && event.cancelable) event.preventDefault();
  }
  function finish(id: number, x: number, y: number, event: Event) {
    const origin = start;
    reset();
    if (!origin || origin.id !== id || !enabled() || selected()) return;
    const dx = x - origin.x,
      dy = y - origin.y;
    if (Math.abs(dx) >= 36 && Math.abs(dx) > Math.abs(dy) * 1.2) {
      // Suppress compatibility mouse clicks after a touch swipe.
      if (event.cancelable) event.preventDefault();
      turn(dx > 0 ? 'prev' : 'next');
    }
  }
  const options = { passive: false, capture: true, signal };
  surface.addEventListener(
    'touchstart',
    (event) => {
      if (event.touches.length !== 1) return reset();
      const touch = event.touches[0];
      begin(touch.identifier, touch.clientX, touch.clientY, event.target);
    },
    options,
  );
  surface.addEventListener(
    'touchmove',
    (event) => {
      if (event.touches.length !== 1) return reset();
      const touch = event.touches[0];
      if (start?.id === touch.identifier) move(touch.clientX, touch.clientY, event);
    },
    options,
  );
  surface.addEventListener(
    'touchend',
    (event) => {
      if (event.touches.length || event.changedTouches.length !== 1) return reset();
      const touch = event.changedTouches[0];
      finish(touch.identifier, touch.clientX, touch.clientY, event);
    },
    options,
  );
  surface.addEventListener('touchcancel', reset, options);

  // Touch pointer events can be cancelled by WebKit while Touch Events continue.
  // They must neither own nor reset the touch gesture state.
  surface.addEventListener(
    'pointerdown',
    (event) => {
      if (event.pointerType !== 'mouse' && event.pointerType !== 'pen') return;
      if (event.pointerType === 'mouse' && (event.button !== 0 || event.shiftKey || event.ctrlKey || event.metaKey)) return;
      pointers.add(event.pointerId);
      if (pointers.size !== 1) return reset();
      begin(event.pointerId, event.clientX, event.clientY, event.target);
      if (!start) return;
      event.preventDefault();
      try {
        surface.setPointerCapture(event.pointerId);
      } catch {
        /* Pointer capture is optional for mouse and pen. */
      }
    },
    options,
  );
  surface.addEventListener(
    'pointermove',
    (event) => {
      if (pointers.has(event.pointerId) && start?.id === event.pointerId) move(event.clientX, event.clientY, event);
    },
    options,
  );
  surface.addEventListener(
    'pointerup',
    (event) => {
      if (!pointers.delete(event.pointerId)) return;
      if (!pointers.size) finish(event.pointerId, event.clientX, event.clientY, event);
      else reset();
    },
    options,
  );
  const cancelPointer = (event: PointerEvent) => {
    if (!pointers.delete(event.pointerId)) return;
    reset();
  };
  surface.addEventListener('pointercancel', cancelPointer, options);
  surface.addEventListener('lostpointercapture', cancelPointer, options);
}
