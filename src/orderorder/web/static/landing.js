/* The landing story in motion: stamps landing on the page, numerals counting up, bars filling.
 *
 * Every element this file touches is complete before it arrives -- the counts are typeset at their
 * final values, the bars at their full widths, the stamps sitting square -- because the story has to
 * read with scripts off, on a train, under `prefers-reduced-motion`. This file only *replays* the
 * page: it hides what it is about to reveal at the moment of revealing it, never in the stylesheet,
 * which is also what keeps the strict CSP intact (GSAP writes through the CSSOM, which `style-src`
 * does not govern).
 */
(function () {
  "use strict";

  var reduced = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (reduced || typeof window.gsap === "undefined") return;

  var gsap = window.gsap;
  gsap.registerPlugin(window.ScrollTrigger);
  var ScrollTrigger = window.ScrollTrigger;

  /* The failure-mode stamps: cards land slightly out of true and square up as they enter, the way a
   * rubber stamp settles on paper. Batched so a fast scroll reveals a row at a time. */
  ScrollTrigger.batch(".stamp", {
    once: true,
    start: "top 88%",
    onEnter: function (batch) {
      gsap.from(batch, {
        y: 26,
        opacity: 0,
        rotate: function () { return gsap.utils.random(-4, 4); },
        duration: 0.55,
        stagger: 0.05,
        ease: "back.out(1.6)",
        overwrite: true,
      });
    },
  });

  /* The corpus numerals count up from zero when the ink band enters. The final value lives in
   * data-count and in the text node itself, so no script means the right number is simply there. */
  document.querySelectorAll(".numbers .numeral").forEach(function (el) {
    var target = parseInt(el.getAttribute("data-count"), 10);
    if (!target) return;
    var state = { v: 0 };
    ScrollTrigger.create({
      trigger: el,
      start: "top 88%",
      once: true,
      onEnter: function () {
        gsap.to(state, {
          v: target,
          duration: 1.6,
          ease: "power2.out",
          onUpdate: function () { el.textContent = Math.round(state.v).toLocaleString("en-US"); },
        });
      },
    });
  });

  /* The three states rise in order, supported first -- the order the footer argues them in. */
  ScrollTrigger.create({
    trigger: ".states",
    start: "top 85%",
    once: true,
    onEnter: function () {
      gsap.from(".state", { y: 22, opacity: 0, duration: 0.5, stagger: 0.12, ease: "power2.out", overwrite: true });
    },
  });

  /* The bars fill to the widths the stylesheet already declares; the CSS classes are the truth and
   * the animation only replays toward them, so no script means full, honest bars. */
  ScrollTrigger.create({
    trigger: ".bars",
    start: "top 85%",
    once: true,
    onEnter: function () {
      document.querySelectorAll(".bar-fill").forEach(function (fill, i) {
        var to = getComputedStyle(fill).width;
        gsap.fromTo(fill, { width: 0 }, { width: to, duration: 0.9, delay: 0.06 * i, ease: "power3.out" });
      });
    },
  });

  /* Section headings rise as they enter, quietly; the page speaks before it moves. */
  ScrollTrigger.batch(".story-head", {
    once: true,
    start: "top 90%",
    onEnter: function (batch) {
      gsap.from(batch, { y: 18, opacity: 0, duration: 0.6, stagger: 0.08, ease: "power2.out", overwrite: true });
    },
  });
})();
