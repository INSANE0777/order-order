// Ruchi — Landing Page Script
// Lenis + GSAP Smooth Scroll, Interactive Simulator, and Cinematic Transitions.
// Strict CSP: script-src 'self', zero inline scripts or styles.

(() => {
  const $ = (id) => document.getElementById(id);
  const finePointer = matchMedia("(pointer: fine)").matches;
  const prefersStill = matchMedia("(prefers-reduced-motion: reduce)").matches;

  // ---------- Lenis Smooth Scroll + GSAP ScrollTrigger ----------
  let lenis;
  if (typeof Lenis !== "undefined" && typeof gsap !== "undefined" && !prefersStill) {
    lenis = new Lenis({
      lerp: 0.08,
      smoothWheel: true,
      wheelMultiplier: 0.92,
      touchMultiplier: 1.4,
    });

    if (typeof ScrollTrigger !== "undefined") {
      gsap.registerPlugin(ScrollTrigger);
      lenis.on("scroll", ScrollTrigger.update);
    }

    lenis.on("scroll", (e) => {
      document.body.dataset.scrolled = e.scroll > 8 ? "1" : "0";
    });

    gsap.ticker.add((time) => {
      lenis.raf(time * 1000);
    });
    gsap.ticker.lagSmoothing(0);

    // Smooth anchor navigation
    document.querySelectorAll('a[href^="#"]').forEach((anchor) => {
      anchor.addEventListener("click", (e) => {
        const href = anchor.getAttribute("href");
        if (href && href !== "#") {
          const target = document.querySelector(href);
          if (target) {
            e.preventDefault();
            lenis.scrollTo(target, { offset: -74, duration: 1.15, easing: (t) => Math.min(1, 1.001 - Math.pow(2, -10 * t)) });
          }
        }
      });
    });

    // GSAP ScrollTrigger choreographies
    gsap.from(".hero-title", { opacity: 0, y: 24, duration: 0.9, ease: "power3.out" });
    gsap.from(".hero-lede", { opacity: 0, y: 18, duration: 0.85, delay: 0.12, ease: "power3.out" });
    gsap.from(".hero-ctas, .proof-bar", { opacity: 0, y: 16, duration: 0.8, delay: 0.22, ease: "power3.out" });
    gsap.from(".monolith-stack", { opacity: 0, scale: 0.94, y: 32, duration: 1.1, delay: 0.25, ease: "power3.out" });

    if (typeof ScrollTrigger !== "undefined") {
      // 12 Traps grid reveal
      gsap.from(".traps-grid .trap-card", {
        scrollTrigger: {
          trigger: ".traps-grid",
          start: "top 85%",
        },
        opacity: 0,
        y: 28,
        stagger: 0.04,
        duration: 0.7,
        ease: "power3.out",
      });

      // Integrity ladder reveal
      gsap.from(".ladder-step", {
        scrollTrigger: {
          trigger: ".ladder-container",
          start: "top 82%",
        },
        opacity: 0,
        x: -22,
        stagger: 0.07,
        duration: 0.75,
        ease: "power3.out",
      });

      // Architecture grid reveal
      gsap.from(".arch-card", {
        scrollTrigger: {
          trigger: ".arch-grid",
          start: "top 85%",
        },
        opacity: 0,
        y: 24,
        stagger: 0.09,
        duration: 0.75,
        ease: "power3.out",
      });

      window.addEventListener("load", () => {
        ScrollTrigger.refresh();
      });
      window.lenis = lenis;
    }
  } else {
    // Fallback native scroll handler
    let queued = false;
    const updateScroll = () => {
      queued = false;
      document.body.dataset.scrolled = window.scrollY > 8 ? "1" : "0";
    };
    window.addEventListener("scroll", () => {
      if (!queued) {
        queued = true;
        requestAnimationFrame(updateScroll);
      }
    }, { passive: true });
    updateScroll();
  }

  // ---------- Signature Segmented Tabs & Scroll Synchronization ----------
  const landingTabs = [
    { id: "tab-verify", key: "verify", target: "#demo" },
    { id: "tab-traps", key: "traps", target: "#traps" },
    { id: "tab-integrity", key: "integrity", target: "#ladder" },
  ];

  const thumb = document.querySelector(".tabs .thumb");

  function switchTab(key, smoothScroll = true) {
    document.body.dataset.landingTab = key;
    landingTabs.forEach((t) => {
      const btn = $(t.id);
      if (btn) {
        const active = t.key === key;
        btn.classList.toggle("on", active);
        btn.setAttribute("aria-selected", active ? "true" : "false");
      }
    });
    if (thumb) {
      thumb.classList.remove("moving");
      void thumb.offsetWidth;
      thumb.classList.add("moving");
      setTimeout(() => thumb.classList.remove("moving"), 420);
    }
  }

  landingTabs.forEach((tab) => {
    const btn = $(tab.id);
    if (btn) {
      btn.addEventListener("click", () => {
        switchTab(tab.key);
        const targetEl = document.querySelector(tab.target);
        if (targetEl) {
          if (window.lenis) {
            window.lenis.scrollTo(targetEl, { offset: -80, duration: 1.2 });
          } else {
            targetEl.scrollIntoView({ behavior: "smooth" });
          }
        }
      });
    }
  });

  // Scroll synchronization with ScrollTrigger
  if (typeof ScrollTrigger !== "undefined" && !prefersStill) {
    ScrollTrigger.create({
      trigger: "#traps",
      start: "top 40%",
      end: "bottom 40%",
      onEnter: () => switchTab("traps"),
      onEnterBack: () => switchTab("traps"),
      onLeaveBack: () => switchTab("verify"),
    });

    ScrollTrigger.create({
      trigger: "#ladder",
      start: "top 40%",
      end: "bottom 10%",
      onEnter: () => switchTab("integrity"),
      onEnterBack: () => switchTab("integrity"),
      onLeaveBack: () => switchTab("traps"),
    });
  }

  // ---------- Live Corpus Health Telemetry ----------
  fetch("/api/health")
    .then((r) => (r.ok ? r.json() : null))
    .then((d) => {
      const st = $("status-text");
      if (st && d) {
        if (d.judgments_with_text) {
          st.textContent = `${d.judgments_with_text.toLocaleString()} indexed`;
        } else if (d.corpus_ready) {
          st.textContent = "corpus ready";
        }
      }
    })
    .catch(() => {});

  // ---------- User Profile Inspection ----------
  fetch("/api/auth/me")
    .then((r) => (r.ok ? r.json() : null))
    .then((d) => {
      if (d && d.user) {
        const pill = $("user-profile");
        const name = $("user-name");
        const loginBtn = $("nav-login");
        if (pill && name) {
          name.textContent = d.user.full_name || d.user.email;
          pill.hidden = false;
        }
        if (loginBtn) loginBtn.hidden = true;
      }
    })
    .catch(() => {});

  const logoutBtn = $("btn-logout");
  if (logoutBtn) {
    logoutBtn.addEventListener("click", async () => {
      await fetch("/api/auth/logout", { method: "POST" });
      window.location.reload();
    });
  }

  // ---------- BFCache & Back-Button Safe State Reset ----------
  function resetTransitionState() {
    const curtain = $("dossier-curtain");
    if (curtain) {
      if (typeof gsap !== "undefined") {
        gsap.killTweensOf([curtain, "main", ".nav", ".curtain-content"]);
        gsap.set(curtain, { y: "100%", clearProps: "transform" });
        gsap.set("main, .nav", {
          opacity: 1,
          y: 0,
          scale: 1,
          filter: "none",
          clearProps: "all",
        });
      } else {
        curtain.style.transform = "translateY(100%)";
        const main = document.querySelector("main");
        const nav = document.querySelector(".nav");
        if (main) { main.style.opacity = "1"; main.style.transform = "none"; main.style.filter = "none"; }
        if (nav) { nav.style.opacity = "1"; nav.style.transform = "none"; }
      }
    }
    if (window.lenis) {
      window.lenis.start();
      window.lenis.resize();
    }
    if (typeof ScrollTrigger !== "undefined") {
      ScrollTrigger.refresh();
    }
  }

  // Reset state on initial execution and on every pageshow/popstate
  resetTransitionState();
  window.addEventListener("pageshow", () => resetTransitionState());
  window.addEventListener("popstate", () => resetTransitionState());

  // ---------- Measured & Cinematic "Sign In" Transition Chain ----------
  const signinLinks = document.querySelectorAll('a[href="/login"]');
  signinLinks.forEach((link) => {
    link.addEventListener("click", (e) => {
      if (prefersStill || typeof gsap === "undefined") return;
      e.preventDefault();

      const href = link.getAttribute("href") || "/login";
      const curtain = $("dossier-curtain");
      if (!curtain) {
        window.location.href = href;
        return;
      }

      const tl = gsap.timeline({
        onComplete: () => {
          window.location.href = href;
        },
      });

      // 1. Tactile click feedback (0.22s)
      tl.to(link, {
        scale: 0.94,
        duration: 0.22,
        ease: "power2.out",
      })
      // 2. Main content & nav smoothly blur and retreat into background (0.75s)
      .to("main, .nav", {
        opacity: 0.08,
        y: -30,
        filter: "blur(5px)",
        duration: 0.75,
        ease: "power2.inOut",
      }, 0.12)
      // 3. Physical legal dossier curtain rises from below (0.85s)
      .fromTo(curtain,
        { y: "100%" },
        { y: "0%", duration: 0.85, ease: "power3.inOut" },
        0.18
      )
      // 4. Stately pause for visual comprehension (0.2s)
      .to({}, { duration: 0.2 });
    });
  });

  // ---------- 3D Hero Monolith Parallax Tilt ----------
  if (finePointer && !prefersStill) {
    const monolith = $("monolith");
    if (monolith) {
      const hero = monolith.closest(".hero-section");
      if (hero) {
        hero.addEventListener("pointermove", (e) => {
          const r = hero.getBoundingClientRect();
          const x = (e.clientX - r.left) / r.width - 0.5;
          const y = (e.clientY - r.top) / r.height - 0.5;
          monolith.style.setProperty("--tx", `${(x * 12).toFixed(2)}deg`);
          monolith.style.setProperty("--ty", `${(-y * 10).toFixed(2)}deg`);
        });
        hero.addEventListener("pointerleave", () => {
          monolith.style.setProperty("--tx", "0deg");
          monolith.style.setProperty("--ty", "0deg");
        });
      }
    }
  }

  // ---------- Simulator Presets & Logic ----------
  const PRESETS = {
    dominus: {
      text: "It is submitted at the outset that the plaintiff is dominus litis and cannot be compelled to implead a subsequent purchaser against whom he does not want to fight: 2019 INSC 770, para 7.",
      grade: "D",
      gradeText: "Grade D · Misattributed Advocate Submission",
      quote: "“Mr. Dushyant Dave, learned Senior Counsel appearing for the appellant, vehemently submitted that the plaintiff being the dominus litis cannot be compelled to fight against someone against whom he seeks no relief.”",
      finding: "Mode 05 (Voice Inversion): The sentence cited is located under Section III ('Submissions of Counsel') at paragraph 7. At paragraph 28, the Supreme Court held the contrary: a subsequent purchaser holding a prior agreement to sell is a necessary party to avoid multiplicity of proceedings.",
      attack: "Opposing counsel will cite paragraph 28 of the same judgment to prove your submission relies on an advocate's argument that the Supreme Court rejected on the merits."
    },
    kesavananda: {
      text: "The power of amendment under Article 368 does not enable Parliament to alter the basic structure or framework of the Constitution: (1973) 4 SCC 225, para 316.",
      grade: "A",
      gradeText: "Grade A · Direct Binding Constitutional Precedent",
      quote: "“The power of amendment under Article 368 does not enable Parliament to alter the basic structure or framework of the Constitution.” — Para 316, per Majority (13-Judge Bench).",
      finding: "Mode 00 (Binding Precedent): Verbatim match against the official SCR judgment text. Rendered by a 13-Judge Constitution Bench. Unchallenged binding authority under Article 141.",
      attack: "Opposing counsel cannot assail the precedent directly. Their defense will be restricted to arguing that the impugned enactment regulates administrative execution rather than violating an essential feature of the basic structure."
    },
    laches: {
      text: "The doctrine of delay and laches cannot be applied stricto senso to writ petitions invoking public interest jurisdiction: 2024 INSC 1027, para 17.",
      grade: "C",
      gradeText: "Grade C · Obiter Dictum / Qualifying Reservation",
      quote: "“While the principle of laches is an equitable doctrine that courts exercise with restraint in matters of broad public interest, it cannot be relaxed where innocent third-party rights have intervened.”",
      finding: "Mode 04 (Qualified Context): The proposition omits the Court's explicit qualifying proviso. The exception applies strictly where third-party rights have not crystalised.",
      attack: "Opposing counsel will demonstrate that third-party rights and commercial agreements were executed over the multi-year delay, defeating the exception invoked from 2024 INSC 1027."
    }
  };

  let activePresetKey = "dominus";

  function setPreset(key) {
    const p = PRESETS[key];
    if (!p) return;
    activePresetKey = key;

    const input = $("sim-input");
    if (input) input.value = p.text;

    document.querySelectorAll(".sim-preset").forEach(btn => {
      btn.classList.toggle("on", btn.dataset.preset === key);
    });

    // Reset visual state before run
    const stair = $("sim-stair");
    if (stair) stair.dataset.grade = "";
    const badge = $("sim-badge");
    if (badge) badge.innerHTML = `<span class="g">–</span> <b id="sim-grade-text">Pending scan</b>`;
    $("sim-status").textContent = "Click 'Run Verification Pass' to test";
  }

  function runSimulation() {
    const p = PRESETS[activePresetKey];
    if (!p) return;

    $("sim-status").textContent = "Resolving SCR citation…";
    $("sim-run").disabled = true;

    setTimeout(() => {
      $("sim-status").textContent = "Scanning paragraph rhetorical roles…";
      const stair = $("sim-stair");
      if (stair) stair.dataset.grade = p.grade;

      const badge = $("sim-badge");
      if (badge) {
        badge.innerHTML = `<span class="g ${p.grade}">${p.grade}</span> <b>${p.gradeText}</b>`;
      }

      $("sim-quote").textContent = p.quote;
      $("sim-finding").textContent = p.finding;
      $("sim-attack").textContent = p.attack;
      $("sim-status").textContent = "Verification complete";
      $("sim-run").disabled = false;
    }, 450);
  }

  // Bind Preset Buttons
  document.querySelectorAll(".sim-preset").forEach(btn => {
    btn.addEventListener("click", () => {
      setPreset(btn.dataset.preset);
      runSimulation();
    });
  });

  const runBtn = $("sim-run");
  if (runBtn) {
    runBtn.addEventListener("click", runSimulation);
  }

  // Initialize with first preset
  setPreset("dominus");
  runSimulation();
})();
