const cars = [
  { id: 1, title: "Toyota Camry 2.5", type: "sedan", year: 2022, km: 32000, engine: "2.5 бензин", price: 2890000, emoji: "🚗" },
  { id: 2, title: "Kia Sportage 2.0", type: "suv", year: 2023, km: 18000, engine: "2.0 бензин", price: 3150000, emoji: "🚙" },
  { id: 3, title: "BMW 530i M Sport", type: "premium", year: 2021, km: 45000, engine: "2.0 турбо", price: 4690000, emoji: "🏎" },
  { id: 4, title: "Volkswagen Golf 1.4", type: "hatchback", year: 2020, km: 56000, engine: "1.4 TSI", price: 1790000, emoji: "🚗" },
  { id: 5, title: "Hyundai Tucson 2.0", type: "suv", year: 2022, km: 27000, engine: "2.0 бензин", price: 2990000, emoji: "🚙" },
  { id: 6, title: "Mercedes E 200 4MATIC", type: "premium", year: 2022, km: 30000, engine: "2.0 турбо", price: 6250000, emoji: "🏎" },
  { id: 7, title: "Lada Vesta Sport", type: "sedan", year: 2023, km: 12000, engine: "1.8 бензин", price: 1450000, emoji: "🚗" },
  { id: 8, title: "Skoda Octavia 1.4", type: "sedan", year: 2021, km: 41000, engine: "1.4 TSI", price: 1990000, emoji: "🚗" },
  { id: 9, title: "Toyota RAV4 Hybrid", type: "suv", year: 2023, km: 15000, engine: "2.5 гибрид", price: 3890000, emoji: "🚙" },
];

const cardsEl = document.getElementById("cards");
const carSelect = document.getElementById("carSelect");
const fmt = (n) => n.toLocaleString("ru-RU") + " ₽";

function render(filter = "all") {
  cardsEl.innerHTML = "";
  cars
    .filter((c) => filter === "all" || c.type === filter)
    .forEach((c) => {
      const card = document.createElement("div");
      card.className = "card";
      card.innerHTML = `
        <div class="card__img">${c.emoji}</div>
        <div class="card__body">
          <h3 class="card__title">${c.title}</h3>
          <div class="card__specs">
            <span>${c.year} год</span>
            <span>${c.km.toLocaleString("ru-RU")} км</span>
            <span>${c.engine}</span>
          </div>
          <div class="card__price">${fmt(c.price)}</div>
          <button class="btn btn--primary" data-buy="${c.id}">Записаться на просмотр</button>
        </div>`;
      cardsEl.appendChild(card);
    });
}

document.querySelectorAll(".filter").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelector(".filter.active").classList.remove("active");
    btn.classList.add("active");
    render(btn.dataset.filter);
  });
});

cars.forEach((c) => {
  const opt = document.createElement("option");
  opt.value = c.title;
  opt.textContent = c.title;
  carSelect.appendChild(opt);
});

document.addEventListener("click", (e) => {
  const id = e.target.dataset.buy;
  if (id) {
    const car = cars.find((c) => c.id === +id);
    carSelect.value = car.title;
    document.getElementById("contacts").scrollIntoView({ behavior: "smooth" });
  }
});

/* Credit calculator */
const price = document.getElementById("price");
const down = document.getElementById("down");
const months = document.getElementById("months");
const rate = 0.099 / 12; // 9.9% годовых

function calc() {
  const p = +price.value;
  const d = Math.min(+down.value, p * 0.7);
  const m = +months.value;
  document.getElementById("priceOut").textContent = fmt(p);
  document.getElementById("downOut").textContent = fmt(d);
  document.getElementById("monthsOut").textContent = m + " мес.";
  const loan = p - d;
  const payment =
    (loan * rate) / (1 - Math.pow(1 + rate, -m));
  document.getElementById("payment").textContent =
    Math.round(payment).toLocaleString("ru-RU") + " ₽";
}
[price, down, months].forEach((el) => el.addEventListener("input", calc));
calc();

/* Form */
document.getElementById("form").addEventListener("submit", (e) => {
  e.preventDefault();
  document.getElementById("success").hidden = false;
  e.target.reset();
});

/* Mobile nav */
document.getElementById("burger").addEventListener("click", () => {
  document.getElementById("nav").classList.toggle("open");
});
document.querySelectorAll(".nav a").forEach((a) =>
  a.addEventListener("click", () => document.getElementById("nav").classList.remove("open"))
);

render();
