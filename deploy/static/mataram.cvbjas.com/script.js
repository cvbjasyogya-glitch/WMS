const brandData = {
  mataram: {
    name: "Mataram Sports",
    logo: "assets/logo-mataram.png",
    theme: "mataram",
    heroTitle: 'Perlengkapan Olahraga <span>Terlengkap</span> di Yogyakarta',
    heroSubtitle:
      "Mataram Sports hadir sebagai pusat kebutuhan olahraga dengan layanan profesional, produk pilihan, dan pengalaman belanja yang nyaman.",
    heroOverviewEyebrow: "Mataram Sports & Mega Sports",
    heroOverviewSubtitle:
      "Mataram Sports dan Mega Sports hadir untuk melayani kebutuhan olahraga dengan pengalaman belanja yang nyaman, cepat, dan profesional.",
    exploreTitle: "Jelajahi Mataram Sports",
    exploreSubtitle: "Akses cepat ke layanan, katalog, promo, brand, dan informasi toko.",
    brandSectionText: "Berbagai brand olahraga yang tersedia dan kami tangani di Mataram Sports.",
    serviceTitle: "Layanan Mataram Sports",
    serviceText:
      "Mataram Sports membantu kebutuhan olahraga harian hingga kebutuhan tim dengan pelayanan responsif, pilihan produk yang relevan, dan dukungan pembelian online maupun offline.",
    aboutTitle: "Tentang Mataram Sports",
    aboutText:
      "Mataram Sports merupakan toko olahraga yang melayani kebutuhan perlengkapan olahraga untuk individu, komunitas, sekolah, kantor, dan event.",
    addressLabel: "Alamat Mataram Sports",
    address: "Jl. Mataram No 64, Danurejan Yogyakarta",
    whatsapp: "0813 - 1946 - 6464",
    whatsappUrl: "https://wa.me/6281319466464",
    instagram: "@mataramsports",
    instagramUrl: "https://instagram.com/mataramsports",
    hours: "Setiap hari, 08.00 - 21.00 WIB",
    mapEmbed: "https://www.google.com/maps?q=-7.7937272,110.3678964&z=18&output=embed",
    mapUrl:
      "https://www.google.com/maps/place/Mataram+Sport/@-7.7937283,110.3666571,18z/data=!4m6!3m5!1s0x2e7a5828629b23eb:0xdf0c5d31ac83c080!8m2!3d-7.7937272!4d110.3678964!16s%2Fg%2F1hm4mws0t",
    careerTitle: "Karier di Mataram Sports",
    careerText: "Bergabung bersama tim Mataram Sports dan ikut berkembang dalam industri retail olahraga.",
    footerDescription:
      "Mataram Sports hadir sebagai pintu utama kebutuhan olahraga, layanan toko, promo, brand, dan informasi resmi CV Berkah Jaya Abadi Sports.",
    copyright: "\u00a9 2026 Mataram Sports - CV Berkah Jaya Abadi Sports. All Rights Reserved.",
  },
  mega: {
    name: "Mega Sports",
    logo: "assets/logo-mega.png",
    theme: "mega",
    heroTitle: "Mega Sports, Pilihan Perlengkapan Olahraga Modern",
    heroSubtitle:
      "Mega Sports hadir untuk kebutuhan olahraga harian, komunitas, sekolah, dan event dengan produk pilihan serta layanan toko yang responsif.",
    heroOverviewEyebrow: "Mega Sports",
    heroOverviewSubtitle:
      "Mega Sports hadir untuk melayani kebutuhan olahraga dengan pengalaman belanja yang nyaman, cepat, dan profesional.",
    exploreTitle: "Jelajahi Mega Sports",
    exploreSubtitle: "Akses cepat ke katalog, promo, layanan, brand, dan informasi Mega Sports.",
    brandSectionText: "Berbagai brand olahraga yang tersedia dan kami tangani di Mega Sports.",
    serviceTitle: "Layanan Mega Sports",
    serviceText:
      "Mega Sports membantu kebutuhan olahraga harian, komunitas, sekolah, dan event dengan pelayanan responsif serta pilihan produk yang beragam.",
    aboutTitle: "Tentang Mega Sports",
    aboutText:
      "Mega Sports merupakan toko olahraga yang melayani kebutuhan perlengkapan olahraga dengan pendekatan modern, pilihan produk yang beragam, dan pengalaman belanja yang nyaman.",
    addressLabel: "Alamat Mega Sports",
    address: "Jl Seturan Raya Blok C1, Ruko Villa Indah, Caturtunggal, Depok, Sleman",
    whatsapp: "0813 - 1946 - 6565",
    whatsappUrl: "https://wa.me/6281319466464",
    instagram: "@megasports",
    instagramUrl: "https://instagram.com/megasports",
    hours: "Setiap hari, 08.00 - 21.00 WIB",
    mapEmbed: "https://www.google.com/maps?q=-7.7699467,110.4097625&z=19&output=embed",
    mapUrl:
      "https://www.google.com/maps/place/Mega+Sport/@-7.7699454,110.4091188,19z/data=!3m1!4b1!4m6!3m5!1s0x2e7a5993964d9ced:0xc0018d0dcc15b034!8m2!3d-7.7699467!4d110.4097625!16s%2Fg%2F11bwh8lxb7",
    careerTitle: "Karier di Mega Sports",
    careerText: "Bergabung bersama tim Mega Sports dan ikut berkembang dalam industri retail olahraga.",
    footerDescription:
      "Mega Sports hadir sebagai bagian dari CV Berkah Jaya Abadi Sports untuk melayani kebutuhan perlengkapan olahraga secara modern dan profesional.",
    copyright: "\u00a9 2026 Mega Sports - CV Berkah Jaya Abadi Sports. All Rights Reserved.",
  },
};

const setText = (selector, value) => {
  const element = document.querySelector(selector);
  if (element) element.textContent = value;
};

const setHtml = (selector, value) => {
  const element = document.querySelector(selector);
  if (element) element.innerHTML = value;
};

const setHref = (selector, value) => {
  document.querySelectorAll(selector).forEach((element) => {
    element.href = value;
  });
};

const TRANSITION_DURATION = 420;
const CONTENT_SWAP_DELAY = 180;
const prefersReducedMotion = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;

let brandTransitionTimers = [];

const clearBrandTransitionTimers = () => {
  brandTransitionTimers.forEach((timer) => window.clearTimeout(timer));
  brandTransitionTimers = [];
};

function updateTransitionLogo(brand) {
  const overlayLogo = document.querySelector(".brand-transition-mark img");
  if (!overlayLogo || !brandData[brand]) return;

  overlayLogo.src = brandData[brand].logo;
  overlayLogo.alt = brandData[brand].name;
}

function updateBrandContent(brand) {
  const selectedBrand = brandData[brand] ? brand : "mataram";
  const data = brandData[selectedBrand];

  document.body.setAttribute("data-brand", selectedBrand);
  localStorage.setItem("selectedBrand", selectedBrand);
  document.title = `${data.name} | Official Website`;

  document.querySelectorAll("[data-brand-logo]").forEach((logo) => {
    logo.src = data.logo;
    logo.alt = data.name;
  });

  const homeLink = document.querySelector("[data-brand-home-link]");
  if (homeLink) homeLink.setAttribute("aria-label", `${data.name} Beranda`);

  const heroSection = document.querySelector("[data-hero-section]");
  if (heroSection) heroSection.setAttribute("aria-label", `Highlight ${data.name}`);

  const statsGrid = document.querySelector("[data-stats-grid]");
  if (statsGrid) statsGrid.setAttribute("aria-label", `Statistik ${data.name}`);

  setText("[data-hero-brand-name]", data.name);
  setHtml("[data-hero-title]", data.heroTitle);
  setText("[data-hero-subtitle]", data.heroSubtitle);
  setText("[data-hero-overview-eyebrow]", data.heroOverviewEyebrow);
  setText("[data-hero-overview-subtitle]", data.heroOverviewSubtitle);
  setText("[data-explore-title]", data.exploreTitle);
  setText("[data-explore-subtitle]", data.exploreSubtitle);
  setText("[data-brand-section-text]", data.brandSectionText);
  setText("[data-service-title]", data.serviceTitle);
  setText("[data-service-text]", data.serviceText);
  setText("[data-about-title]", data.aboutTitle);
  setText("[data-about-text]", data.aboutText);
  setText("[data-address-label]", data.addressLabel);
  setText("[data-address]", data.address);
  setText("[data-whatsapp]", data.whatsapp);
  setText("[data-instagram]", data.instagram);
  setText("[data-hours]", data.hours);
  setText("[data-career-title]", data.careerTitle);
  setText("[data-career-text]", data.careerText);
  setText("[data-footer-description]", data.footerDescription);
  setText("[data-copyright]", data.copyright);

  const mapIframe = document.querySelector("[data-map-iframe]");
  if (mapIframe) mapIframe.src = data.mapEmbed;

  const mapLink = document.querySelector("[data-map-link]");
  if (mapLink) mapLink.href = data.mapUrl;

  setHref("[data-whatsapp-link]", data.whatsappUrl);
  setHref("[data-instagram-link]", data.instagramUrl);

  document.querySelectorAll("[data-switch-brand]").forEach((button) => {
    const isActive = button.dataset.switchBrand === selectedBrand;
    button.classList.toggle("active", isActive);
    button.setAttribute("aria-pressed", String(isActive));
  });
}

function applyBrandInstant(brand) {
  clearBrandTransitionTimers();
  const selectedBrand = brandData[brand] ? brand : "mataram";

  document.body.classList.remove("is-brand-switching");
  document.querySelector(".brand-transition-overlay")?.classList.remove("is-active");
  updateTransitionLogo(selectedBrand);
  updateBrandContent(selectedBrand);
}

function applyBrand(brand) {
  const selectedBrand = brandData[brand] ? brand : "mataram";
  const currentBrand = document.body.getAttribute("data-brand") || "mataram";

  if (currentBrand === selectedBrand && !document.body.classList.contains("is-brand-switching")) return;

  if (prefersReducedMotion()) {
    applyBrandInstant(selectedBrand);
    return;
  }

  const overlay = document.querySelector(".brand-transition-overlay");

  clearBrandTransitionTimers();
  updateTransitionLogo(selectedBrand);

  document.body.classList.add("is-brand-switching");
  overlay?.classList.add("is-active");

  brandTransitionTimers.push(
    window.setTimeout(() => {
      updateBrandContent(selectedBrand);
      updateTransitionLogo(selectedBrand);
    }, CONTENT_SWAP_DELAY)
  );

  brandTransitionTimers.push(
    window.setTimeout(() => {
      document.body.classList.remove("is-brand-switching");
      overlay?.classList.remove("is-active");
      brandTransitionTimers = [];
    }, TRANSITION_DURATION)
  );
}

document.addEventListener("DOMContentLoaded", () => {
  const header = document.getElementById("siteHeader");
  const menuToggle = document.getElementById("menuToggle");
  const mainMenu = document.getElementById("mainMenu");
  const slides = Array.from(document.querySelectorAll(".hero__slide"));
  const dots = Array.from(document.querySelectorAll("#heroDots button"));
  const prevButton = document.getElementById("heroPrev");
  const nextButton = document.getElementById("heroNext");

  let currentSlide = 0;
  let carouselTimer = null;
  const savedBrand = localStorage.getItem("selectedBrand") || "mataram";

  applyBrandInstant(savedBrand);

  document.querySelectorAll("[data-switch-brand]").forEach((button) => {
    button.addEventListener("click", () => {
      applyBrand(button.dataset.switchBrand);
    });
  });

  const setHeaderState = () => {
    if (!header) return;
    header.classList.toggle("is-scrolled", window.scrollY > 8);
  };

  const closeMenu = () => {
    if (!mainMenu || !menuToggle) return;
    mainMenu.classList.remove("is-open");
    menuToggle.classList.remove("is-open");
    menuToggle.setAttribute("aria-expanded", "false");
  };

  const openMenu = () => {
    if (!mainMenu || !menuToggle) return;
    mainMenu.classList.add("is-open");
    menuToggle.classList.add("is-open");
    menuToggle.setAttribute("aria-expanded", "true");
  };

  const showSlide = (index) => {
    if (!slides.length) return;
    currentSlide = (index + slides.length) % slides.length;

    slides.forEach((slide, slideIndex) => {
      const isActive = slideIndex === currentSlide;
      slide.classList.toggle("active", isActive);
      slide.setAttribute("aria-hidden", String(!isActive));
    });

    dots.forEach((dot, dotIndex) => {
      dot.classList.toggle("active", dotIndex === currentSlide);
    });
  };

  const nextSlide = () => showSlide(currentSlide + 1);
  const prevSlide = () => showSlide(currentSlide - 1);

  const startCarousel = () => {
    if (carouselTimer || slides.length <= 1) return;
    carouselTimer = window.setInterval(nextSlide, 5000);
  };

  const resetCarousel = () => {
    window.clearInterval(carouselTimer);
    carouselTimer = null;
    startCarousel();
  };

  if (menuToggle && mainMenu) {
    menuToggle.addEventListener("click", () => {
      const expanded = menuToggle.getAttribute("aria-expanded") === "true";
      expanded ? closeMenu() : openMenu();
    });

    document.addEventListener("click", (event) => {
      if (!mainMenu.classList.contains("is-open")) return;
      const clickedInsideMenu = mainMenu.contains(event.target);
      const clickedToggle = menuToggle.contains(event.target);
      if (!clickedInsideMenu && !clickedToggle) closeMenu();
    });

    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") closeMenu();
    });
  }

  prevButton?.addEventListener("click", () => {
    prevSlide();
    resetCarousel();
  });

  nextButton?.addEventListener("click", () => {
    nextSlide();
    resetCarousel();
  });

  dots.forEach((dot, index) => {
    dot.addEventListener("click", () => {
      showSlide(index);
      resetCarousel();
    });
  });

  document.querySelectorAll('a[href^="#"]').forEach((link) => {
    link.addEventListener("click", (event) => {
      const targetId = link.getAttribute("href");
      if (!targetId || targetId === "#") return;

      const target = document.querySelector(targetId);
      if (!target) return;

      event.preventDefault();
      closeMenu();
      target.scrollIntoView({ behavior: "smooth", block: "start" });
      window.history.pushState(null, "", targetId);
    });
  });

  const localNavLinks = Array.from(document.querySelectorAll(".navbar__menu .nav-link[href^='#']"));
  const observedSections = localNavLinks
    .map((link) => document.querySelector(link.getAttribute("href")))
    .filter(Boolean);

  if ("IntersectionObserver" in window && observedSections.length) {
    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (!entry.isIntersecting) return;

          localNavLinks.forEach((link) => {
            link.classList.toggle("active", link.getAttribute("href") === `#${entry.target.id}`);
          });
        });
      },
      {
        rootMargin: "-42% 0px -48% 0px",
        threshold: 0,
      }
    );

    observedSections.forEach((section) => observer.observe(section));
  }

  window.addEventListener("scroll", setHeaderState, { passive: true });
  setHeaderState();
  showSlide(0);
  startCarousel();
});
