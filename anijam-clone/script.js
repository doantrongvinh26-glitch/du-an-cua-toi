// Hero carousel: slide 3-at-a-time, looping.
(function heroCarousel() {
  const track = document.querySelector(".hero-track");
  const slides = Array.from(track.children);
  const dotsWrap = document.querySelector(".hero-dots");
  const prevBtn = document.querySelector(".hero-nav.prev");
  const nextBtn = document.querySelector(".hero-nav.next");

  const perView = 3;
  const pageCount = Math.max(1, slides.length - perView + 1);
  let index = 0;

  for (let i = 0; i < pageCount; i++) {
    const dot = document.createElement("span");
    if (i === 0) dot.classList.add("active");
    dot.addEventListener("click", () => goTo(i));
    dotsWrap.appendChild(dot);
  }

  function render() {
    const slideWidth = slides[0].getBoundingClientRect().width + 12;
    track.style.transform = `translateX(${-index * slideWidth}px)`;
    [...dotsWrap.children].forEach((d, i) => d.classList.toggle("active", i === index));
  }

  function goTo(i) {
    index = (i + pageCount) % pageCount;
    render();
  }

  prevBtn.addEventListener("click", () => goTo(index - 1));
  nextBtn.addEventListener("click", () => goTo(index + 1));
  window.addEventListener("resize", render);
  render();
})();

// Inspiration masonry: generate placeholder cards with varied aspect ratios.
(function masonry() {
  const ratios = [
    ["16 / 9", "16:9"], ["4 / 3", "4:3"], ["1 / 1", "1:1"],
    ["21 / 9", "21:9"], ["9 / 16", "9:16"], ["3 / 4", "3:4"],
    ["9 / 21", "9:21"], ["16 / 9", "16:9"], ["4 / 3", "4:3"],
    ["1 / 1", "1:1"], ["21 / 9", "21:9"], ["9 / 16", "9:16"],
  ];
  const wrap = document.getElementById("masonry");
  ratios.forEach(([ratio, label]) => {
    const div = document.createElement("div");
    div.className = "masonry-item";
    div.style.aspectRatio = ratio;
    div.textContent = label;
    wrap.appendChild(div);
  });
})();
