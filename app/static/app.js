(() => {
  const { width: W, height: H, palette, cooldown } = window.PW;
  const canvas = document.getElementById("board");
  const ctx = canvas.getContext("2d");
  const frame = canvas.parentElement;
  const cursor = document.getElementById("cursor");
  const $ = (id) => document.getElementById(id);

  let version = -1;
  let colour = 5;
  let readyAt = 0;
  let zoom = 1, panX = 0, panY = 0;
  const replicas = new Map(); // hostname -> request count
  let lastReplica = "";

  // ---------- drawing ----------
  const image = ctx.createImageData(W, H);
  const rgb = palette.map((h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16)));

  function draw(pixels) {
    for (let i = 0; i < pixels.length; i++) {
      const [r, g, b] = rgb[parseInt(pixels[i], 16)];
      image.data.set([r, g, b, 255], i * 4);
    }
    ctx.putImageData(image, 0, 0);
  }

  function paintLocal(x, y, c) {
    ctx.fillStyle = palette[c];
    ctx.fillRect(x, y, 1, 1);
  }

  // ---------- zoom & pan ----------
  function applyTransform() {
    const max = frame.clientWidth * (zoom - 1);
    panX = Math.min(0, Math.max(-max, panX));
    panY = Math.min(0, Math.max(-max, panY));
    canvas.style.transform = `translate(${panX}px, ${panY}px) scale(${zoom})`;
  }

  frame.addEventListener("wheel", (e) => {
    e.preventDefault();
    const rect = frame.getBoundingClientRect();
    const mx = e.clientX - rect.left, my = e.clientY - rect.top;
    const next = Math.min(8, Math.max(1, zoom * (e.deltaY < 0 ? 1.2 : 1 / 1.2)));
    panX = mx - ((mx - panX) * next) / zoom;
    panY = my - ((my - panY) * next) / zoom;
    zoom = next;
    applyTransform();
    moveCursor(e);
  }, { passive: false });

  function cellAt(e) {
    const rect = frame.getBoundingClientRect();
    const cell = (frame.clientWidth * zoom) / W;
    const x = Math.floor((e.clientX - rect.left - panX) / cell);
    const y = Math.floor((e.clientY - rect.top - panY) / cell);
    return x >= 0 && y >= 0 && x < W && y < H ? { x, y, cell } : null;
  }

  function moveCursor(e) {
    const p = cellAt(e);
    if (!p) { cursor.style.display = "none"; return; }
    Object.assign(cursor.style, {
      display: "block",
      left: `${p.x * p.cell + panX}px`,
      top: `${p.y * p.cell + panY}px`,
      width: `${p.cell}px`,
      height: `${p.cell}px`,
      background: palette[colour] + "aa",
    });
    $("coords").textContent = `x ${p.x}, y ${p.y}`;
  }
  frame.addEventListener("mousemove", moveCursor);
  frame.addEventListener("mouseleave", () => (cursor.style.display = "none"));

  // ---------- palette ----------
  document.querySelectorAll(".swatch").forEach((btn) =>
    btn.addEventListener("click", () => {
      document.querySelector(".swatch.active")?.classList.remove("active");
      btn.classList.add("active");
      colour = +btn.dataset.c;
    })
  );

  // ---------- painting ----------
  frame.addEventListener("click", async (e) => {
    const p = cellAt(e);
    if (!p) return;
    if (Date.now() < readyAt) return toast("Cooling down…");
    paintLocal(p.x, p.y, colour); // optimistic
    try {
      const res = await fetch("/api/pixel", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ x: p.x, y: p.y, c: colour }),
      });
      trackReplica(res);
      const data = await res.json();
      if (res.ok) {
        startCooldown(data.cooldown);
      } else {
        if (data.retry_in) startCooldown(data.retry_in);
        toast(data.error === "cooldown" ? `Wait ${data.retry_in}s` : data.error || "Rejected");
        version = -1; // force a full refresh to undo the optimistic pixel
      }
    } catch {
      toast("Server unreachable");
    }
  });

  function startCooldown(seconds) {
    readyAt = Date.now() + seconds * 1000;
    const total = seconds * 1000;
    const tick = () => {
      const left = readyAt - Date.now();
      if (left <= 0) {
        $("cd-bar").style.width = "100%";
        $("cd-text").textContent = "READY";
        return;
      }
      $("cd-bar").style.width = `${100 - (left / total) * 100}%`;
      $("cd-text").textContent = `${(left / 1000).toFixed(1)}s`;
      requestAnimationFrame(tick);
    };
    tick();
  }

  // ---------- live sync ----------
  async function poll() {
    try {
      const res = await fetch(`/api/board?since=${version}`, { cache: "no-store" });
      trackReplica(res);
      if (res.status === 200) {
        const data = await res.json();
        version = data.version;
        draw(data.pixels);
        $("version").textContent = version;
      }
      $("status").textContent = "live";
      $("status").className = "live";
    } catch {
      $("status").textContent = "reconnecting…";
      $("status").className = "down";
    }
    setTimeout(poll, 1000);
  }

  async function stats() {
    try {
      const res = await fetch("/api/stats", { cache: "no-store" });
      trackReplica(res);
      const s = await res.json();
      $("placed").textContent = s.pixels_placed.toLocaleString();
      $("storage").textContent = s.storage.replace("Store", "");
    } catch {}
    setTimeout(stats, 3000);
  }

  // ---------- replica tracker ----------
  function trackReplica(res) {
    const host = res.headers.get("X-Served-By");
    if (!host) return;
    replicas.set(host, (replicas.get(host) || 0) + 1);
    lastReplica = host;
    renderReplicas();
  }

  function renderReplicas() {
    const max = Math.max(...replicas.values());
    $("replicas").innerHTML = [...replicas.entries()]
      .sort()
      .map(([h, n]) => `
        <li class="${h === lastReplica ? "now" : ""}">
          <span class="name" title="${h}">${h.slice(0, 12)}</span>
          <span class="bar" style="width:${(n / max) * 100}%"></span>
          <span>${n}</span>
        </li>`)
      .join("");
  }

  // ---------- toast ----------
  let toastTimer;
  function toast(msg) {
    document.querySelector(".toast")?.remove();
    const el = Object.assign(document.createElement("div"), { className: "toast", textContent: msg });
    document.body.appendChild(el);
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.remove(), 1600);
  }

  poll();
  stats();
})();
