// ================= SCROLL EFFECTS (shared across all pages) =================
document.addEventListener("DOMContentLoaded", function () {

    // ---------- Scroll progress bar ----------
    var progress = document.createElement("div");
    progress.id = "scrollProgress";
    document.body.appendChild(progress);

    function updateProgress() {
        var scrollTop = window.scrollY || document.documentElement.scrollTop;
        var docHeight = document.documentElement.scrollHeight - window.innerHeight;
        var pct = docHeight > 0 ? (scrollTop / docHeight) * 100 : 0;
        progress.style.width = pct + "%";
    }

    // ---------- Navbar shrink on scroll ----------
    var navbar = document.querySelector(".navbar");

    function updateNavbar() {
        if (!navbar) return;
        if (window.scrollY > 40) {
            navbar.classList.add("scrolled");
        } else {
            navbar.classList.remove("scrolled");
        }
    }

    // ---------- Back to top button ----------
    var backToTop = document.createElement("button");
    backToTop.id = "backToTop";
    backToTop.type = "button";
    backToTop.title = "Back to top";
    backToTop.innerHTML = "&uarr;";
    document.body.appendChild(backToTop);

    backToTop.addEventListener("click", function () {
        window.scrollTo({ top: 0, behavior: "smooth" });
    });

    function updateBackToTop() {
        if (window.scrollY > 400) {
            backToTop.classList.add("show");
        } else {
            backToTop.classList.remove("show");
        }
    }

    // ---------- Scroll reveal (IntersectionObserver) ----------
    var revealTargets = document.querySelectorAll("[data-reveal], [data-reveal-group]");

    if ("IntersectionObserver" in window && revealTargets.length) {
        var observer = new IntersectionObserver(function (entries) {
            entries.forEach(function (entry) {
                if (entry.isIntersecting) {
                    entry.target.classList.add("is-visible");
                    observer.unobserve(entry.target);
                }
            });
        }, { threshold: 0.15, rootMargin: "0px 0px -40px 0px" });

        revealTargets.forEach(function (el) {
            observer.observe(el);
        });
    } else {
        // Fallback: just show everything if IO isn't supported
        revealTargets.forEach(function (el) {
            el.classList.add("is-visible");
        });
    }

    // ---------- Smooth anchor scrolling with sticky-navbar offset ----------
    document.querySelectorAll('a[href^="#"]').forEach(function (link) {
        link.addEventListener("click", function (e) {
            var targetId = link.getAttribute("href");
            if (targetId.length < 2) return;
            var target = document.querySelector(targetId);
            if (!target) return;
            e.preventDefault();
            var offset = navbar ? navbar.offsetHeight : 0;
            var top = target.getBoundingClientRect().top + window.scrollY - offset - 10;
            window.scrollTo({ top: top, behavior: "smooth" });
        });
    });

    // ---------- Listeners ----------
    function onScroll() {
        updateProgress();
        updateNavbar();
        updateBackToTop();
    }

    window.addEventListener("scroll", onScroll, { passive: true });
    onScroll();
});
