// AI Assassin
// Copyright (c) 2026 l2xl (l2xl/at/proton.me)
// Distributed under the Intellectual Property Reserve License, v2 (IPRL)

/**
 * Returns the outcome of one surf action played in the page -- `query`, `fill`, `mouse`, `mask` or `paint` -- or `{error}`, or `{hidden}` where
 * the page is not visible. It is injected by `scripting.executeScript` into the extension's isolated world, so it is self-contained: it
 * sees the page's DOM, not its scripts, and keeps the pointer in that world's globals from one request to the next while the document
 * lives. In the top frame it plays only in a visible document of the origin `options.origin` names, so what it acts on is what the
 * harness judged; taking the masks away plays anywhere.
 */
export async function pageAction(action, options) {
  const MAX_CHARS = 200000;
  const REDACTED = '[redacted]';
  const CREDENTIALS = ['current-password', 'new-password', 'one-time-code', 'cc-number', 'cc-csc', 'cc-exp', 'cc-exp-month', 'cc-exp-year'];
  const DROPPED = ['script', 'style', 'noscript', 'template'];
  const VOID = ['area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'source', 'track', 'wbr'];
  const TEXTUAL = ['text', 'search', 'email', 'url', 'tel', 'number', 'date', 'time', 'datetime-local', 'month', 'week'];
  const STEPS = ['move', 'down', 'up', 'click', 'dblclick', 'wheel', 'pause'];
  // name: [MouseEvent.button, its bit in MouseEvent.buttons]
  const BUTTONS = { left: [0, 1], middle: [1, 4], right: [2, 2] };
  const MAX_STEPS = 100, MAX_MOVES = 100, MAX_PAUSE_MS = 2000, MAX_PAUSES_MS = 10000;

  /** Returns why the top frame refuses an action meant for a page of `origin` -- its page hidden, or of another origin -- else null, as in a subframe. */
  function refusal(origin) {
    if (window.top !== window) return null;
    if (document.visibilityState !== 'visible') return { hidden: 'its page is not visible' };
    const told = (name) => (!name || name === 'null' ? 'a page of no origin' : name);
    if (location.origin === origin) return null;
    return { error: `the surf tab's page is on ${told(location.origin)}, not ${told(origin)}: check it and repeat the call with its origin` };
  }

  /** Whether the element holds a credential: a password or hidden input, a credential- or card-autocompleting field, a token meta. */
  function sensitive(el) {
    if (el.localName === 'meta') return /csrf|token/i.test(el.getAttribute('name') || '');
    if (el.localName !== 'input' && el.localName !== 'textarea') return false;
    const autocomplete = (el.getAttribute('autocomplete') || '').toLowerCase().split(/\s+/);
    return el.type === 'password' || el.type === 'hidden' || autocomplete.some((token) => CREDENTIALS.includes(token));
  }

  /** Returns the live DOM of the selector's matches in document order, or of the whole document, serialized and cut to `max_chars`. */
  function query({ selector, max_chars: wanted }) {
    const limit = Number.isInteger(wanted) && wanted > 0 ? Math.min(wanted, MAX_CHARS) : MAX_CHARS;
    const roots = selector ? [...document.querySelectorAll(selector)] : [document.documentElement];
    const parts = [];
    let length = 0;
    const push = (text) => { parts.push(text); length += text.length; };
    const escape = (text) => text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    const quote = (text) => String(text).replace(/&/g, '&amp;').replace(/"/g, '&quot;');
    const attributes = (el) => {
      const tag = el.localName, live = new Map();
      if (tag === 'input' && (el.type === 'checkbox' || el.type === 'radio')) live.set('checked', el.checked);
      else if (tag === 'input') live.set('value', el.value);
      if (tag === 'option') live.set('selected', el.selected);
      if (tag !== 'textarea' && sensitive(el)) live.set(tag === 'meta' ? 'content' : 'value', REDACTED);
      let text = '';
      for (const { name, value } of el.attributes) if (!live.has(name)) text += ` ${name}="${quote(value)}"`;
      for (const [name, value] of live) if (value !== false) text += value === true ? ` ${name}` : ` ${name}="${quote(value)}"`;
      return text;
    };
    const serialize = (node) => {
      if (length > limit) return;
      if (node.nodeType === 3) {
        const text = node.data.replace(/\s+/g, ' ');
        if (text.trim()) push(escape(text));
        return;
      }
      if (node.nodeType !== 1 || DROPPED.includes(node.localName)) return;
      const tag = node.localName;
      push(`<${tag}${attributes(node)}>`);
      if (VOID.includes(tag)) return;
      if (tag === 'textarea') {
        push(escape(sensitive(node) ? REDACTED : node.value));
      } else if (tag !== 'svg') {
        if (node.shadowRoot) {
          push('<template shadowrootmode="open">');
          node.shadowRoot.childNodes.forEach(serialize);
          push('</template>');
        }
        node.childNodes.forEach(serialize);
      }
      push(`</${tag}>`);
    };
    roots.forEach((root, index) => {
      if (index) push('\n');
      serialize(root);
    });
    const dom = parts.join('');
    return { dom: dom.slice(0, limit), matches: roots.length, truncated: dom.length > limit };
  }

  /** Sets the value of the first element the selector matches as typing does; refuses what is no text field, text area, select or editable element, a disabled or read-only one and a sensitive one. */
  function fill({ selector, value }) {
    const el = document.querySelector(selector);
    if (!el) throw new Error(`no element matches ${selector}`);
    const tag = el.localName;
    const editable = el.isContentEditable && !['input', 'textarea', 'select'].includes(tag);
    if (sensitive(el)) throw new Error(`${selector} is a sensitive field: credentials are typed by the user, never filled`);
    if (!editable && tag !== 'textarea' && tag !== 'select' && !(tag === 'input' && TEXTUAL.includes(el.type))) {
      throw new Error(`${selector} is no text field, text area, select or editable element`);
    }
    if (el.disabled || el.readOnly) throw new Error(`${selector} is disabled or read-only`);
    let text = String(value);
    if (tag === 'select') {
      const options = [...el.options];
      const option = options.find((o) => o.value === text) || options.find((o) => o.label.trim() === text.trim());
      if (!option) throw new Error(`${selector} has no option of value or label ${text}`);
      text = option.value;
    }
    el.focus();
    if (editable) {
      el.textContent = text;
    } else {
      // the prototype's setter, past a framework's own `value` property, so the framework sees the change
      let proto = Object.getPrototypeOf(el);
      while (proto && !Object.getOwnPropertyDescriptor(proto, 'value')) proto = Object.getPrototypeOf(proto);
      Object.getOwnPropertyDescriptor(proto, 'value').set.call(el, text);
    }
    el.dispatchEvent(new InputEvent('input', { bubbles: true, inputType: 'insertText', data: text }));
    el.dispatchEvent(new Event('change', { bubbles: true }));
    return {};
  }

  /** Returns the text fields under `root`, inside its shadow roots too -- closed ones where the browser lets an extension reach them. */
  function fields(root) {
    const closed = globalThis.chrome && chrome.dom && chrome.dom.openOrClosedShadowRoot
      ? (el) => chrome.dom.openOrClosedShadowRoot(el) : (el) => el.openOrClosedShadowRoot;
    const shadows = [...root.querySelectorAll('*')].map((el) => el.shadowRoot || closed(el)).filter(Boolean);
    return [...root.querySelectorAll('input, textarea'), ...shadows.flatMap(fields)];
  }

  /**
   * Lays an opaque box over every visible sensitive field, in the top layer above any dialog, or takes the boxes away; returns the viewport
   * size and scale. It awaits no frame: a frame out of sight never renders one, so the top frame's `paint` awaits them for the capture.
   */
  function mask({ on }) {
    if (globalThis.__websurfMask) globalThis.__websurfMask.remove();
    globalThis.__websurfMask = null;
    let masked = 0;
    if (on) {
      const layer = document.createElement('div');
      layer.setAttribute('popover', 'manual');
      layer.style.cssText = 'position:fixed;inset:0;width:100vw;height:100vh;max-width:none;max-height:none;margin:0;padding:0;border:0;'
        + 'background:transparent;overflow:visible;pointer-events:none;z-index:2147483647';
      for (const el of fields(document)) {
        const r = el.getBoundingClientRect();
        if (!sensitive(el) || r.width <= 0 || r.height <= 0 || r.bottom <= 0 || r.right <= 0 || r.top >= window.innerHeight || r.left >= window.innerWidth) continue;
        const box = document.createElement('div');
        box.style.cssText = `position:absolute;left:${r.left}px;top:${r.top}px;width:${r.width}px;height:${r.height}px;background:#000`;
        layer.appendChild(box);
        masked += 1;
      }
      if (masked) {
        document.documentElement.appendChild(layer);
        globalThis.__websurfMask = layer;
        // a popover not shown is hidden: without the top layer the boxes stay plain, above all but dialogs
        try { layer.showPopover(); } catch (e) { layer.removeAttribute('popover'); }
      }
    }
    return { viewport: { width: window.innerWidth, height: window.innerHeight }, scale: window.devicePixelRatio, masked };
  }

  /** Resolves once the masks laid are painted, by the second frame of the top frame -- found visible, so its frames come. */
  async function paint() {
    await new Promise((resolve) => { requestAnimationFrame(() => requestAnimationFrame(resolve)); });
    return {};
  }

  /** Plays the mouse steps as the user's pointer would, from where the previous request left it -- the centre of the viewport after a load. */
  async function mouse({ steps }) {
    if (!Array.isArray(steps) || !steps.length || steps.length > MAX_STEPS) throw new Error(`a mouse request holds 1 to ${MAX_STEPS} steps`);
    const targeted = (step) => Boolean(step.selector) || (Number.isFinite(step.x) && Number.isFinite(step.y));
    steps.forEach((step, index) => {
      if (!step || !STEPS.includes(step.type)) throw new Error(`step ${index + 1}: unknown type ${step && step.type}`);
      if (['move', 'click', 'dblclick'].includes(step.type) && !targeted(step)) throw new Error(`step ${index + 1}: ${step.type} needs x and y or a selector`);
      if (step.button !== undefined && !Object.hasOwn(BUTTONS, step.button)) throw new Error(`step ${index + 1}: unknown button ${step.button}`);
    });
    const pointer = (globalThis.__websurfPointer ??= { x: window.innerWidth / 2, y: window.innerHeight / 2, buttons: 0, over: null, press: null, drag: null, compat: true });
    let paused = 0;

    /** Returns the element under the pointer, inside open shadow roots. */
    function hit() {
      let el = document.elementFromPoint(pointer.x, pointer.y) || document.documentElement;
      for (let inner; el.shadowRoot && (inner = el.shadowRoot.elementFromPoint(pointer.x, pointer.y)) && inner !== el;) el = inner;
      return el;
    }

    /** Dispatches a pointer, mouse, wheel or drag event at the pointer to `el`; returns whether no listener cancelled it. */
    function fire(el, type, extra = {}) {
      const Kind = type.startsWith('pointer') || ['click', 'auxclick', 'contextmenu'].includes(type) ? PointerEvent
        : type === 'wheel' ? WheelEvent : type.startsWith('drag') || type === 'drop' ? DragEvent : MouseEvent;
      const pointerish = Kind === PointerEvent ? { pointerId: 1, pointerType: 'mouse', isPrimary: true, width: 1, height: 1, pressure: pointer.buttons ? 0.5 : 0 } : {};
      return el.dispatchEvent(new Kind(type, {
        bubbles: true, cancelable: true, composed: true, view: window, detail: 0, clientX: pointer.x, clientY: pointer.y,
        screenX: pointer.x, screenY: pointer.y, button: 0, buttons: pointer.buttons, ...pointerish, ...extra,
      }));
    }

    /** Returns `el` and its ancestors up to the first that contains `other`, innermost first. */
    function chain(el, other) {
      const list = [];
      for (let n = el; n && !(other && n.contains(other)); n = n.parentElement) list.push(n);
      return list;
    }

    /** Moves the hover to `el`: the out and leave events of the element hovered before, then the over and enter events of `el`. */
    function hover(el) {
      const old = pointer.over && pointer.over.isConnected ? pointer.over : null;
      if (old === el) return;
      const left = chain(old, el), entered = chain(el, old).reverse(), quiet = { bubbles: false, cancelable: false };
      for (const kind of ['pointer', 'mouse']) {
        if (old) fire(old, `${kind}out`, { relatedTarget: el });
        for (const n of left) fire(n, `${kind}leave`, { ...quiet, relatedTarget: el });
        fire(el, `${kind}over`, { relatedTarget: old });
        for (const n of entered) fire(n, `${kind}enter`, { ...quiet, relatedTarget: old });
      }
      pointer.over = el;
    }

    /** Returns the viewport point of a step's target: its x and y, else the centre of its selector's first match, scrolled into view when outside. */
    function point(step) {
      if (!step.selector) return { x: step.x, y: step.y };
      const el = document.querySelector(step.selector);
      if (!el) throw new Error(`no element matches ${step.selector}`);
      let r = el.getBoundingClientRect();
      const x = r.left + r.width / 2, y = r.top + r.height / 2;
      if (x < 0 || y < 0 || x >= window.innerWidth || y >= window.innerHeight) {
        el.scrollIntoView({ block: 'center', inline: 'center', behavior: 'instant' });
        r = el.getBoundingClientRect();
      }
      return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
    }

    /** Moves the pointer to `to` along a straight path of `count` moves -- pointer and mouse moves, or drag events once a drag has begun. */
    async function moveTo(to, count) {
      const from = { x: pointer.x, y: pointer.y };
      const n = Math.min(Math.max(Math.round(Number(count)) || 10, 1), MAX_MOVES);
      for (let i = 1; i <= n; i += 1) {
        pointer.x = Math.round(from.x + ((to.x - from.x) * i) / n);
        pointer.y = Math.round(from.y + ((to.y - from.y) * i) / n);
        if (pointer.press && !pointer.drag) startDrag();
        const el = hit();
        if (pointer.drag) {
          dragOver(el);
        } else {
          hover(el);
          fire(el, 'pointermove');
          // a cancelled pointerdown keeps the mouse events of its press from firing
          if (!pointer.buttons || pointer.compat) fire(el, 'mousemove');
        }
        // a task between moves, so the page renders what the last one changed before the next one hits
        await new Promise((resolve) => {
          const channel = new MessageChannel();
          channel.port1.onmessage = () => { channel.port1.close(); resolve(); };
          channel.port2.postMessage(0);
        });
      }
    }

    /** Begins an HTML5 drag when the pointer moves with the left button pressed on a draggable element or inside one, unless its dragstart is cancelled. */
    function startDrag() {
      const press = pointer.press;
      if (press.tried || press.button !== 0) return;
      press.tried = true;
      let source = press.target;
      while (source && source.getAttribute('draggable') !== 'true') source = source.parentElement;
      if (!source) return;
      const data = new DataTransfer();
      if (fire(source, 'dragstart', { dataTransfer: data })) pointer.drag = { source, data, over: null, drop: false };
    }

    /** Plays one point of a drag over `el`: drag on the source, dragenter and dragleave where the target changes, then dragover. */
    function dragOver(el) {
      const drag = pointer.drag;
      fire(drag.source, 'drag', { dataTransfer: drag.data });
      if (el !== drag.over) {
        fire(el, 'dragenter', { dataTransfer: drag.data, relatedTarget: drag.over });
        if (drag.over) fire(drag.over, 'dragleave', { dataTransfer: drag.data, cancelable: false, relatedTarget: el });
        drag.over = el;
      }
      drag.drop = !fire(el, 'dragover', { dataTransfer: drag.data });
    }

    /** Ends the drag: drop where the last dragover was cancelled, else dragleave, then dragend on the source. */
    function endDrag() {
      const { source, data, over, drop } = pointer.drag;
      Object.assign(pointer, { drag: null, press: null, buttons: 0, compat: true });
      if (over) fire(over, drop ? 'drop' : 'dragleave', { dataTransfer: data, cancelable: drop });
      fire(source, 'dragend', { dataTransfer: data });
    }

    /** Focuses the nearest focusable element a left press hits, as the browser does on mousedown, or blurs the focus when there is none. */
    function focus(el) {
      for (let n = el; n; n = n.parentElement) {
        const root = n.isContentEditable && !(n.parentElement && n.parentElement.isContentEditable);
        if (!n.disabled && (n.tabIndex >= 0 || n.hasAttribute('tabindex') || root)) return n.focus();
      }
      if (document.activeElement && document.activeElement !== document.body) document.activeElement.blur();
    }

    /** Presses the button where the pointer is: pointerdown and mousedown, focus for a left press, contextmenu for a right one. */
    function press(name, detail) {
      const [button, bit] = BUTTONS[name];
      const el = hit();
      hover(el);
      pointer.buttons |= bit;
      pointer.compat = fire(el, 'pointerdown', { button });
      const focusing = pointer.compat ? fire(el, 'mousedown', { button, detail }) : true;
      if (button === 0 && focusing) focus(el);
      if (button === 2) fire(el, 'contextmenu', { button, detail });
      pointer.press = { button, target: el };
    }

    /** Releases the button where the pointer is: the end of a drag, else pointerup and mouseup, then click or auxclick where the press hit the same element. */
    function release(name, detail) {
      if (pointer.drag) return endDrag();
      const [button, bit] = BUTTONS[name];
      const el = hit();
      hover(el);
      pointer.buttons &= ~bit;
      fire(el, 'pointerup', { button });
      if (pointer.compat) fire(el, 'mouseup', { button, detail });
      const pressed = pointer.press;
      Object.assign(pointer, { press: null, compat: true });
      if (pressed && pressed.button === button && pressed.target === el && button !== 2) fire(el, button === 0 ? 'click' : 'auxclick', { button, detail });
    }

    /** Turns the wheel where the pointer is and, unless cancelled, scrolls the nearest scrollable ancestor, as a synthetic wheel event scrolls nothing. */
    function wheel(dx, dy) {
      const el = hit();
      hover(el);
      if (!fire(el, 'wheel', { deltaX: dx, deltaY: dy, deltaZ: 0, deltaMode: 0 })) return;
      const scrolls = (overflow, size, client) => /auto|scroll|overlay/.test(overflow) && size > client;
      for (let n = el; n && n !== document.body && n !== document.documentElement; n = n.parentElement) {
        const style = window.getComputedStyle(n);
        if ((dy && scrolls(style.overflowY, n.scrollHeight, n.clientHeight)) || (dx && scrolls(style.overflowX, n.scrollWidth, n.clientWidth))) return n.scrollBy(dx, dy);
      }
      window.scrollBy(dx, dy);
    }

    /** Plays one step. */
    async function play(step) {
      const button = step.button || 'left';
      if (step.type === 'pause') {
        const ms = Math.max(0, Math.min(Number(step.ms) || 0, MAX_PAUSE_MS, MAX_PAUSES_MS - paused));
        paused += ms;
        return new Promise((resolve) => setTimeout(resolve, ms));
      }
      if (targeted(step)) await moveTo(point(step), step.count);
      if (step.type === 'down') press(button, 1);
      else if (step.type === 'up') release(button, 1);
      else if (step.type === 'click') { press(button, 1); release(button, 1); }
      else if (step.type === 'dblclick') { press('left', 1); release('left', 1); press('left', 2); release('left', 2); fire(hit(), 'dblclick', { detail: 2 }); }
      else if (step.type === 'wheel') wheel(Number(step.dx) || 0, Number(step.dy) || 0);
    }

    for (const [index, step] of steps.entries()) {
      try {
        await play(step);
      } catch (e) {
        throw new Error(`step ${index + 1} (${step.type}): ${e.message}`);
      }
    }
    return {};
  }

  try {
    const refused = ['query', 'fill', 'mouse', 'mask', 'paint'].includes(action) && !(action === 'mask' && !options.on) && refusal(options.origin);
    if (refused) return refused;
    if (action === 'query') return query(options);
    if (action === 'fill') return fill(options);
    if (action === 'mouse') return await mouse(options);
    if (action === 'mask') return mask(options);
    if (action === 'paint') return await paint();
    return { error: `unknown page action ${action}` };
  } catch (e) {
    return { error: String((e && e.message) || e) };
  }
}
