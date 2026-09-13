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


/* The footer cosmos: cobalt smoke and cream stars drifting behind the card, drawn on the one
 * canvas the page owns. It is decoration and knows it -- aria-hidden in the markup, skipped
 * entirely under reduced motion, and the gradients live here rather than in the stylesheet so the
 * page costs nothing when this file never arrives. */
(function () {
  var canvas = document.getElementById("footer-canvas");
  if (!canvas || reduced) return;
  var ctx = canvas.getContext("2d");
  var width, height, raf;

  function resize() {
    width = canvas.width = canvas.offsetWidth;
    height = canvas.height = canvas.offsetHeight;
  }
  window.addEventListener("resize", resize);
  resize();

  var drift = Array.from({ length: 34 }, function () {
    return {
      x: Math.random() * width, y: Math.random() * height,
      radius: Math.random() * 90 + 50,
      vx: (Math.random() - 0.5) * 0.25, vy: (Math.random() - 0.5) * 0.25,
      alpha: Math.random() * 0.22 + 0.05,
    };
  });
  var stars = Array.from({ length: 90 }, function () {
    return { x: Math.random() * width, y: Math.random() * height, size: Math.random() * 1.7, alpha: Math.random() };
  });

  function frame() {
    ctx.clearRect(0, 0, width, height);
    drift.forEach(function (p) {
      p.x += p.vx; p.y += p.vy;
      if (p.x < -120) p.x = width + 120;
      if (p.x > width + 120) p.x = -120;
      if (p.y < -120) p.y = height + 120;
      if (p.y > height + 120) p.y = -120;
      var g = ctx.createRadialGradient(p.x, p.y, 0, p.x, p.y, p.radius);
      g.addColorStop(0, "rgba(43, 52, 214, " + p.alpha + ")");
      g.addColorStop(0.5, "rgba(26, 33, 153, " + p.alpha * 0.5 + ")");
      g.addColorStop(1, "rgba(0, 0, 0, 0)");
      ctx.fillStyle = g;
      ctx.beginPath();
      ctx.arc(p.x, p.y, p.radius, 0, Math.PI * 2);
      ctx.fill();
    });
    stars.forEach(function (s) {
      s.alpha += (Math.random() - 0.5) * 0.02;
      if (s.alpha < 0.1) s.alpha = 0.1;
      if (s.alpha > 0.85) s.alpha = 0.85;
      ctx.fillStyle = "rgba(243, 236, 229, " + s.alpha * 0.8 + ")";
      ctx.beginPath();
      ctx.arc(s.x, s.y, s.size, 0, Math.PI * 2);
      ctx.fill();
    });
    raf = requestAnimationFrame(frame);
  }
  frame();
})();
