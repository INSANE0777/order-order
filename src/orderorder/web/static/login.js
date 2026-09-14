// Ruchi — Authentication Client Script
// Multi-stage Accreditation Animation Chain & Strict CSP compliance.

(() => {
  const $ = (id) => document.getElementById(id);
  const prefersStill = matchMedia("(prefers-reduced-motion: reduce)").matches;

  let mode = "login"; // "login" | "register"

  // URL query parameter for redirection
  const params = new URLSearchParams(window.location.search);
  const nextUrl = params.get("next") || "/dashboard";

  // ---------- Entrance Animation Chain ----------
  if (typeof gsap !== "undefined" && !prefersStill) {
    const tl = gsap.timeline({ defaults: { ease: "power3.out" } });
    tl.from("#auth-folder", {
      opacity: 0,
      y: 35,
      rotateX: 6,
      transformPerspective: 900,
      duration: 0.8,
    })
    .from(".auth-header .mark .s", {
      y: 8,
      opacity: 0,
      stagger: 0.06,
      duration: 0.45,
    }, 0.15)
    .from(".auth-mode-switch, .auth-title, .auth-desc, .form-group, .form-actions, .auth-foot", {
      opacity: 0,
      y: 16,
      stagger: 0.05,
      duration: 0.55,
    }, 0.2);
  }

  function setMode(newMode) {
    if (mode === newMode) return;
    mode = newMode;
    const isRegister = mode === "register";

    $("mode-login").classList.toggle("on", !isRegister);
    $("mode-register").classList.toggle("on", isRegister);

    $("group-name").hidden = !isRegister;
    $("password-hint").hidden = !isRegister;

    if (isRegister) {
      $("auth-heading").textContent = "Create an advocate account.";
      $("auth-sub").textContent = "Register with your professional email to access citation verification.";
      $("btn-text").textContent = "Create Account";
      $("tab-label").textContent = "REGISTRATION DOSSIER";
      document.title = "Register — Ruchi";
    } else {
      $("auth-heading").textContent = "Access your verification workspace.";
      $("auth-sub").textContent = "Enter your credentials to manage briefs, cite checks, and drafted submissions.";
      $("btn-text").textContent = "Sign In";
      $("tab-label").textContent = "AUTHENTICATION DOSSIER";
      document.title = "Sign In — Ruchi";
    }

    // Smooth text transition
    if (typeof gsap !== "undefined" && !prefersStill) {
      gsap.fromTo(["#auth-heading", "#auth-sub"], { opacity: 0, y: -6 }, { opacity: 1, y: 0, duration: 0.32, ease: "power2.out" });
      if (isRegister) {
        gsap.fromTo("#group-name", { opacity: 0, height: 0 }, { opacity: 1, height: "auto", duration: 0.35, ease: "power2.out" });
      }
    }
    hideAlert();
  }

  function showAlert(msg) {
    const alert = $("auth-alert");
    alert.textContent = msg;
    alert.hidden = false;
    if (typeof gsap !== "undefined" && !prefersStill) {
      gsap.fromTo(alert, { opacity: 0, y: -8, scale: 0.96 }, { opacity: 1, y: 0, scale: 1, duration: 0.3, ease: "back.out(1.5)" });
      gsap.to("#auth-folder", { x: 10, duration: 0.07, repeat: 5, yoyo: true, ease: "power1.inOut", onComplete: () => gsap.set("#auth-folder", { x: 0 }) });
    }
  }

  function hideAlert() {
    $("auth-alert").hidden = true;
  }

  $("mode-login").addEventListener("click", () => setMode("login"));
  $("mode-register").addEventListener("click", () => setMode("register"));

  $("auth-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    hideAlert();

    const email = $("input-email").value.trim();
    const password = $("input-password").value;
    const fullName = $("input-name").value.trim();

    if (!email) {
      showAlert("Please enter your email address.");
      return;
    }
    if (!password) {
      showAlert("Please enter your password.");
      return;
    }
    if (mode === "register" && password.length < 8) {
      showAlert("Password must be at least 8 characters long.");
      return;
    }

    const btn = $("btn-submit");
    btn.disabled = true;
    const origText = $("btn-text").textContent;
    $("btn-text").textContent = mode === "register" ? "Creating Account…" : "Verifying Credentials…";

    // Submit button click press micro-animation
    if (typeof gsap !== "undefined" && !prefersStill) {
      gsap.to(btn, { scale: 0.96, duration: 0.12, yoyo: true, repeat: 1, ease: "power2.inOut" });
    }

    const endpoint = mode === "register" ? "/api/auth/register" : "/api/auth/login";
    const payload = { email, password };
    if (mode === "register") payload.full_name = fullName;

    try {
      const resp = await fetch(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload)
      });
      const data = await resp.json().catch(() => ({}));

      if (!resp.ok) {
        throw new Error(data.detail || `Authentication failed (${resp.status})`);
      }

      // ========== THE ACCREDITATION ANIMATION CHAIN ==========
      if (typeof gsap !== "undefined" && !prefersStill) {
        const seal = $("auth-seal");
        if (seal) {
          seal.classList.add("visible");
          const successTl = gsap.timeline({
            onComplete: () => {
              window.location.href = nextUrl;
            }
          });

          successTl
            .fromTo(seal,
              { opacity: 0, scale: 2.2, rotate: -18 },
              { opacity: 1, scale: 1, rotate: -3, duration: 0.45, ease: "back.out(1.8)" }
            )
            .to(btn, {
              backgroundColor: "var(--good, #4fd39a)",
              color: "#0f1236",
              duration: 0.25,
            }, 0.1)
            .to("#auth-folder", {
              y: -70,
              opacity: 0,
              scale: 0.93,
              duration: 0.55,
              ease: "power3.in",
            }, 0.5);
          return;
        }
      }

      // Instant fallback if motion reduced or gsap missing
      window.location.href = nextUrl;
    } catch (err) {
      showAlert(err.message || "An unexpected error occurred. Please try again.");
      btn.disabled = false;
      $("btn-text").textContent = origText;
    }
  });

  // ---------- Return to Landing Page Transition ----------
  const returnLinks = document.querySelectorAll(".brand-link, #btn-back-landing");
  returnLinks.forEach((link) => {
    link.addEventListener("click", (e) => {
      if (prefersStill || typeof gsap === "undefined") return;
      e.preventDefault();
      const href = link.getAttribute("href") || "/";
      gsap.to("#auth-folder", {
        y: 35,
        opacity: 0,
        rotateX: -3,
        duration: 0.45,
        ease: "power2.in",
        onComplete: () => {
          window.location.href = href;
        },
      });
    });
  });
})();
