/**
 * Helios client — WebSocket state + REST fallback for Reactor Overload / Sabacc.
 * Non-REACTOR stations are local mock demos (labeled).
 */
(function (global) {
  "use strict";

  const RESKIN = {
    FREEZE: "Containment Lock",
    FLIP_THREE: "Overcharge Pulse",
    SECOND_CHANCE: "Neutralizer Shield",
  };

  function wsUrl(role, seat) {
    const proto = location.protocol === "https:" ? "wss:" : "ws:";
    let q = "role=" + encodeURIComponent(role || "table");
    if (seat !== undefined && seat !== null && seat !== "") q += "&seat=" + encodeURIComponent(seat);
    return proto + "//" + location.host + "/ws?" + q;
  }

  function connect(opts) {
    const role = opts.role || "table";
    const seat = opts.seat;
    const onState = opts.onState || function () {};
    const onConn = opts.onConn || function () {};
    const onError = opts.onError || function () {};

    let ws = null;
    let closed = false;
    let retry = 0;
    let pollTimer = null;

    function statePath() {
      let path = "/api/state";
      if (seat !== undefined && seat !== null && seat !== "") {
        path += "?seat=" + encodeURIComponent(seat);
      }
      return path;
    }

    function startPoll() {
      if (pollTimer) return;
      pollTimer = setInterval(function () {
        fetch(statePath())
          .then(function (r) { return r.json(); })
          .then(onState)
          .catch(function () {});
      }, 900);
    }

    function stopPoll() {
      if (pollTimer) {
        clearInterval(pollTimer);
        pollTimer = null;
      }
    }

    function open() {
      if (closed) return;
      try {
        ws = new WebSocket(wsUrl(role, seat));
      } catch (e) {
        onConn(false);
        startPoll();
        return;
      }
      ws.onopen = function () {
        retry = 0;
        onConn(true);
        stopPoll();
      };
      ws.onclose = function () {
        onConn(false);
        startPoll();
        if (!closed) {
          const wait = Math.min(5000, 400 * Math.pow(1.5, retry++));
          setTimeout(open, wait);
        }
      };
      ws.onerror = function () {
        onConn(false);
      };
      ws.onmessage = function (ev) {
        let msg;
        try {
          msg = JSON.parse(ev.data);
        } catch (e) {
          return;
        }
        if (msg.type === "state" && msg.state) onState(msg.state);
        if (msg.type === "error") onError(msg.error || "error");
      };
    }

    function send(obj) {
      if (ws && ws.readyState === 1) {
        ws.send(JSON.stringify(obj));
        return true;
      }
      return false;
    }

    function post(path, body) {
      const payload = body || {};
      if (seat !== undefined && seat !== null && seat !== "" && payload.seat === undefined) {
        payload.seat = seat;
      }
      return fetch(path, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      }).then(function (r) {
        return r.json().then(function (j) {
          if (!r.ok) throw new Error(j.error || r.statusText);
          onState(j);
          return j;
        });
      });
    }

    function hit(s) {
      const seatNum = s !== undefined ? s : seat;
      if (!send({ type: "hit", seat: seatNum })) {
        return post("/api/hit", { seat: seatNum });
      }
      return Promise.resolve();
    }

    function stay(s) {
      const seatNum = s !== undefined ? s : seat;
      if (!send({ type: "stay", seat: seatNum })) {
        return post("/api/stay", { seat: seatNum });
      }
      return Promise.resolve();
    }

    function newMatch(players, game, computers) {
      const payload = { type: "new" };
      if (players) payload.players = players;
      if (game) payload.game = game;
      if (computers !== undefined && computers !== null) payload.computers = computers;
      if (!send(payload)) {
        const body = players ? { players: players } : {};
        if (game) body.game = game;
        if (computers !== undefined && computers !== null) body.computers = computers;
        return post("/api/new", body);
      }
      return Promise.resolve();
    }

    function setGame(game, players, computers) {
      const payload = { type: "set_game", game: game };
      if (players) payload.players = players;
      if (computers !== undefined && computers !== null) payload.computers = computers;
      if (!send(payload)) {
        const body = { game: game };
        if (players) body.players = players;
        if (computers !== undefined && computers !== null) body.computers = computers;
        return post("/api/game", body);
      }
      return Promise.resolve();
    }

    function setComputers(n, players) {
      const payload = { type: "set_computers", computers: n };
      if (players) payload.players = players;
      if (!send(payload)) {
        const body = { computers: n };
        if (players) body.players = players;
        return post("/api/computers", body);
      }
      return Promise.resolve();
    }

    function sell(cardUid, claimId, buyerSeat, s) {
      const seatNum = s !== undefined ? s : seat;
      const payload = {
        type: "sell",
        seat: seatNum,
        card: cardUid,
        claim: claimId,
        buyer: buyerSeat,
      };
      if (!send(payload)) return post("/api/sell", payload);
      return Promise.resolve();
    }

    function look(want, s) {
      const seatNum = s !== undefined ? s : seat;
      const payload = { type: "look", seat: seatNum, look: !!want };
      if (!send(payload)) return post("/api/look", payload);
      return Promise.resolve();
    }

    function endGame(s) {
      const payload = { type: "end" };
      const seatNum = s !== undefined ? s : seat;
      if (seatNum !== undefined && seatNum !== null && seatNum !== "") payload.seat = seatNum;
      if (!send(payload)) return post("/api/end", payload);
      return Promise.resolve();
    }

    function setRole(role, s) {
      const seatNum = s !== undefined ? s : seat;
      const payload = { type: "set_role", seat: seatNum, role: role };
      if (!send(payload)) return post("/api/role", payload);
      return Promise.resolve();
    }

    open();
    fetch(statePath()).then(function (r) { return r.json(); }).then(onState).catch(function () {});

    return {
      hit: hit,
      stay: stay,
      newMatch: newMatch,
      setGame: setGame,
      setComputers: setComputers,
      sell: sell,
      look: look,
      endGame: endGame,
      setRole: setRole,
      close: function () {
        closed = true;
        stopPoll();
        if (ws) try { ws.close(); } catch (e) {}
      },
    };
  }

  function cardShort(label) {
    if (!label || label === "—") return "—";
    if (label === "Containment Lock" || label === "FREEZE") return "LOCK";
    if (label === "Overcharge Pulse" || label === "FLIP_THREE") return "PULSE";
    if (label === "Neutralizer Shield" || label === "SECOND_CHANCE") return "SHIELD";
    if (label === "Sylop" || label === "SYLOP") return "Ø";
    return String(label);
  }

  function isActionLabel(label) {
    return /Lock|Pulse|Shield|FREEZE|FLIP|SECOND|Sylop/i.test(String(label));
  }

  function isSabacc(state) {
    return state && (state.rules === "sabacc" || state.game === "sabacc");
  }

  function isManifest(state) {
    return state && (state.rules === "manifest" || state.game === "manifest");
  }

  function rulesId(state) {
    if (isManifest(state)) return "manifest";
    if (isSabacc(state)) return "sabacc";
    return "flip7";
  }

  function goodName(card) {
    if (!card) return "—";
    if (typeof card === "string") return card;
    return card.name || card.id || "—";
  }

  function uniqueNumbers(hand) {
    const seen = {};
    (hand || []).forEach(function (label) {
      const s = String(label);
      if (/^-?\d+$/.test(s) && Number(s) !== 0) seen[s] = true;
    });
    return Object.keys(seen).length;
  }

  /** Paper score card: number tiles, player totals, heart and star bonus tiles. */
  function scoreModel(state) {
    const rules = rulesId(state);
    const players = (state && state.players) || [];
    const tiles = [];
    let heart = { icon: "♥", label: "Heart", on: false };
    let star = { icon: "★", label: "Star", on: false };

    if (rules === "manifest") {
      const active = players.filter(function (p) { return p.seat === state.active_seat; })[0] || players[0];
      ((active && active.market_lines) || []).forEach(function (line) {
        tiles.push(String(line.points));
      });
      let pair = false;
      let triple = false;
      players.forEach(function (p) {
        (p.market_lines || []).forEach(function (line) {
          const n = Number(line.count) || 0;
          if (n >= 3) triple = true;
          if (n === 2 || n === 4 || n === 5) pair = true;
        });
      });
      heart = { icon: "♥", label: "Pair", on: pair };
      star = { icon: "★", label: "Three", on: triple };
    } else if (rules === "sabacc") {
      (state.hand || []).forEach(function (c) { tiles.push(cardShort(c)); });
      const sum = Number(state.hand_sum || 0);
      const limit = Number(state.bomb_limit || 23);
      const dealt = (state.hand || []).length > 0;
      heart = { icon: "♥", label: "Safe", on: dealt && Math.abs(sum) <= limit };
      star = { icon: "★", label: "Pure", on: dealt && sum === 0 };
    } else {
      (state.hand || []).forEach(function (c) { tiles.push(cardShort(c)); });
      heart = { icon: "♥", label: "Shield", on: !!(state && state.shield) };
      const overload = uniqueNumbers(state && state.hand) >= 7 || /overload/i.test(String((state && state.status) || ""));
      star = { icon: "★", label: "Overload", on: overload };
    }
    if (!tiles.length) tiles.push("—");

    return {
      title: state && state.phase === "won" ? "Final scores" : "Scores",
      tiles: tiles,
      totals: players.map(function (p) {
        return {
          label: "Player " + (Number(p.seat) + 1),
          name: p.name || "",
          score: p.score,
          active: !!p.active,
        };
      }),
      bonuses: [heart, star],
    };
  }

  function renderScoreCard(root, state) {
    if (!root) return;
    const model = scoreModel(state || {});
    root.innerHTML = "";

    const title = document.createElement("h2");
    title.className = "score-card-title";
    title.textContent = model.title;
    root.appendChild(title);

    const strip = document.createElement("div");
    strip.className = "score-tiles";
    model.tiles.forEach(function (n) {
      const tile = document.createElement("div");
      tile.className = "score-tile";
      tile.textContent = n;
      strip.appendChild(tile);
    });
    root.appendChild(strip);

    const list = document.createElement("ul");
    list.className = "score-players";
    model.totals.forEach(function (row) {
      const li = document.createElement("li");
      if (row.active) li.className = "active";
      li.textContent = row.label + (row.name ? " · " + row.name : "") + " — " + row.score;
      list.appendChild(li);
    });
    root.appendChild(list);

    const bonusTitle = document.createElement("h2");
    bonusTitle.className = "score-card-title";
    bonusTitle.textContent = "Bonus";
    root.appendChild(bonusTitle);

    const bonus = document.createElement("div");
    bonus.className = "bonus-row";
    model.bonuses.forEach(function (b) {
      const tile = document.createElement("div");
      tile.className = "bonus-tile" + (b.on ? " on" : "");
      tile.setAttribute("aria-label", b.label + (b.on ? ", on" : ", off"));
      const icon = document.createElement("span");
      icon.className = "bonus-icon";
      icon.textContent = b.icon;
      const cap = document.createElement("span");
      cap.className = "bonus-label";
      cap.textContent = b.label;
      tile.appendChild(icon);
      tile.appendChild(cap);
      bonus.appendChild(tile);
    });
    root.appendChild(bonus);
  }

  function cardPolarity(label) {
    const s = String(label || "");
    if (s === "Sylop" || s === "SYLOP" || s === "Ø" || s === "0") return "sylop";
    if (/^\+\d/.test(s) || (s !== "" && !s.startsWith("-") && /^\d+$/.test(s) && Number(s) > 0))
      return "pos";
    if (/^-\d/.test(s)) return "neg";
    return "";
  }

  /** Station mock helpers (local only) */
  const Stations = {
    weatherTick: function (root) {
      const kp = (Math.random() * 7).toFixed(1);
      const solar = (Math.random() * 100).toFixed(0);
      const kpEl = root.querySelector("[data-kp]");
      const solEl = root.querySelector("[data-solar]");
      const bar = root.querySelector("[data-solar-bar]");
      if (kpEl) kpEl.textContent = kp;
      if (solEl) solEl.textContent = solar + "%";
      if (bar) bar.style.width = solar + "%";
      const blocks = root.querySelectorAll(".kp-blocks i");
      blocks.forEach(function (el, i) {
        el.style.height = 20 + ((Number(kp) * 10 + i * 7) % 70) + "%";
      });
    },
    bioTick: function (root) {
      root.querySelectorAll(".vial").forEach(function (v, i) {
        const alert = Math.random() < 0.12;
        v.classList.toggle("alert", alert);
        const st = v.querySelector(".st");
        if (st) st.textContent = alert ? "ANOMALY" : "STABLE";
      });
    },
  };

  global.Holo = {
    RESKIN: RESKIN,
    connect: connect,
    cardShort: cardShort,
    isActionLabel: isActionLabel,
    isSabacc: isSabacc,
    isManifest: isManifest,
    rulesId: rulesId,
    goodName: goodName,
    scoreModel: scoreModel,
    renderScoreCard: renderScoreCard,
    cardPolarity: cardPolarity,
    Stations: Stations,
  };
})(typeof window !== "undefined" ? window : globalThis);
