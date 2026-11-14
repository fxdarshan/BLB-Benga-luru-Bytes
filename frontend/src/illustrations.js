// Small line drawings for the page's quiet moments: the welcome screen, no matches, the AI being
// busy, and errors. Fixed markup only, never data. The styles colour them from the theme, so they
// suit both the dark and the light theme.

const DRAWINGS = {
  // A steaming bowl on a plate, in front of a small Bangalore skyline.
  welcome: `
    <g class="ill-faint">
      <path d="M12 100V74h13v26M25 100V60h12v40M37 100V80h10v20"/>
      <path d="M31 60v-7M31 53l-3 3M31 53l3 3"/>
      <path d="M152 100V68h12v32M164 100V54h11l4 6v40M179 100V76h11v24"/>
      <path d="M8 100h184"/>
    </g>
    <path class="ill-fill" d="M56 76h88a44 26 0 0 1-88 0z"/>
    <g class="ill-line">
      <path d="M56 76h88a44 26 0 0 1-88 0z"/>
      <path d="M40 104h120"/>
      <path d="M86 64c-6-7 6-11 0-19M100 60c-6-7 6-11 0-19M114 64c-6-7 6-11 0-19"/>
    </g>
    <g class="ill-spark">
      <path d="M46 34l2 5 5 2-5 2-2 5-2-5-5-2 5-2z"/>
      <path d="M150 26l1.5 3.5 3.5 1.5-3.5 1.5-1.5 3.5-1.5-3.5-3.5-1.5 3.5-1.5z"/>
    </g>`,

  // An empty plate between a fork and a knife, and a magnifying glass.
  empty: `
    <ellipse class="ill-fill" cx="100" cy="80" rx="48" ry="15"/>
    <g class="ill-line">
      <ellipse cx="100" cy="80" rx="48" ry="15"/>
      <ellipse cx="100" cy="80" rx="28" ry="8"/>
      <path d="M36 50v42M30 50v11a6 6 0 0 0 12 0V50"/>
      <path d="M166 50c-6 4-8 12-8 21h8v21"/>
    </g>
    <g class="ill-faint">
      <circle cx="146" cy="30" r="10"/>
      <path d="M153 37l8 8"/>
    </g>`,

  // A pot on the boil, with a small clock: the AI needs a minute.
  busy: `
    <path class="ill-fill" d="M62 60h76v30a10 10 0 0 1-10 10H72a10 10 0 0 1-10-10z"/>
    <g class="ill-line">
      <path d="M62 60h76v30a10 10 0 0 1-10 10H72a10 10 0 0 1-10-10z"/>
      <path d="M62 68h-9M138 68h9"/>
      <path d="M57 60h86M93 60v-6h14v6"/>
      <path d="M84 44c-5-6 5-9 0-15M100 40c-5-6 5-9 0-15M116 44c-5-6 5-9 0-15"/>
    </g>
    <g class="ill-faint">
      <circle cx="164" cy="34" r="12"/>
      <path d="M164 27v7l5 3"/>
    </g>`,

  // A plug that has come out of its socket.
  error: `
    <rect class="ill-fill" x="58" y="46" width="30" height="32" rx="6"/>
    <g class="ill-line">
      <rect x="58" y="46" width="30" height="32" rx="6"/>
      <path d="M66 46v-9M80 46v-9"/>
      <path d="M73 78c0 18-26 14-38 26"/>
      <rect x="120" y="40" width="34" height="44" rx="8"/>
      <path d="M131 56v8M143 56v8"/>
    </g>
    <g class="ill-spark">
      <path d="M98 52l8-5M97 62h10M98 72l8 5"/>
    </g>`,
};

/** An illustration as an SVG element. Decorative, so hidden from screen readers. */
export function illustration(name, { size = "large" } = {}) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.setAttribute("viewBox", "0 0 200 112");
  svg.setAttribute("class", `illustration illustration-${size}`);
  svg.setAttribute("fill", "none");
  svg.setAttribute("stroke-width", "2.5");
  svg.setAttribute("stroke-linecap", "round");
  svg.setAttribute("stroke-linejoin", "round");
  svg.setAttribute("aria-hidden", "true");
  svg.innerHTML = DRAWINGS[name] ?? "";
  return svg;
}
