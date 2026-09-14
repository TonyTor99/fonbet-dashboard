"""
Движок бэктеста. Читает snapshot-БД только на чтение и считает метрики.

Единица ставки для market/period: на каждый матч (event_id) берётся ПЕРВЫЙ снимок,
удовлетворяющий {момент входа + диапазон кф + лига + даты} → одна ставка, результат из r_*.
Для signals — готовые записи стратегии (профит считаем сами из odds+result).
"""
import os
import sqlite3
import datetime

from sources import SOURCES, META_COLS, market_by_code

WEEKDAYS_RU = ["Пн", "Вт", "Ср", "Чт", "Пт", "Сб", "Вс"]

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SNAP_DIR = os.path.join(BASE_DIR, "snapshots")

WIN, LOSE, PUSH = "Выигрыш", "Проигрыш", "Возврат"


def _connect(source_key):
    db = SOURCES[source_key]["db"]
    path = os.path.join(SNAP_DIR, db)
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    con.row_factory = sqlite3.Row
    return con


def _profit(result, odds, stake):
    if result == WIN:
        return stake * (float(odds) - 1.0)
    if result == LOSE:
        return -stake
    return 0.0  # Возврат / прочее


# Дефолтный «запас» сигнала по лиге (значения из бота fonbet-ipbl).
# Сигнал даётся при 2*сумма_к_перерыву - линия <= запас (запас отрицательный).
def _default_zapas(league):
    lg = league or ""
    women = "Женщин" in lg
    if "Prime" in lg:
        return -14 if women else -10
    if "Pro" in lg:
        return -16 if women else -13
    return None  # неизвестная лига — запас не применяем


# --- Метаданные источника (для UI и валидации) -------------------------------

def source_meta(source_key):
    src = SOURCES[source_key]
    con = _connect(source_key)
    table = src["table"]
    out = {
        "key": source_key, "label": src["label"], "kind": src["kind"],
        "markets": src["markets"], "entry_points": src["entry_points"],
    }
    if src["kind"] == "signals":
        out["leagues"] = [r[0] for r in con.execute(
            "SELECT DISTINCT league FROM signals WHERE league IS NOT NULL ORDER BY 1")]
        # Дефолтный «запас» по каждой лиге (порог сигнала бота: 2*сумма - линия <= запас)
        out["zapas_default"] = {lg: _default_zapas(lg) for lg in out["leagues"]}
        # число решённых матчей (уникальных) — для инфо
        out["matches"] = con.execute(
            "SELECT COUNT(DISTINCT event_id) FROM signals "
            "WHERE result IN ('%s','%s')" % (WIN, LOSE)).fetchone()[0]
        dr = con.execute("SELECT MIN(date(created_at)), MAX(date(created_at)) FROM signals").fetchone()
    else:
        out["leagues"] = [r[0] for r in con.execute(
            f"SELECT league, COUNT(DISTINCT event_id) c FROM {table} "
            f"WHERE league IS NOT NULL GROUP BY league ORDER BY c DESC")]
        out["matches"] = con.execute(f"SELECT COUNT(DISTINCT event_id) FROM {table}").fetchone()[0]
        dr = con.execute(f"SELECT MIN(date(created_at)), MAX(date(created_at)) FROM {table}").fetchone()
        # Доступные значения линий по каждой колонке рынка (для чекбоксов форы и
        # подсказки диапазона тоталов/инд.тоталов).
        line_cols = sorted({m["line"] for m in src["markets"] if m.get("line")})
        out["line_values"] = {
            col: [r[0] for r in con.execute(
                f"SELECT DISTINCT {col} FROM {table} WHERE {col} IS NOT NULL ORDER BY {col}")]
            for col in line_cols
        }
    out["date_from"], out["date_to"] = dr[0], dr[1]
    # Реальные пары (встречи), порядок команд не важен — для фильтра пар.
    seen, pairs = set(), []
    for a, b in con.execute(
        f"SELECT DISTINCT team1, team2 FROM {table} "
        f"WHERE team1 IS NOT NULL AND team1 <> '' AND team2 IS NOT NULL AND team2 <> ''"):
        key = tuple(sorted([a, b]))
        if key in seen:
            continue
        seen.add(key)
        pairs.append([key[0], key[1]])
    pairs.sort()
    out["pairs"] = pairs
    con.close()
    return out


# --- Фильтр по парам, времени и статистика пар --------------------------------

def _pair_where(pairs):
    """pairs: [[teamA, teamB], ...]. Матч подходит, если это ровно эта пара
    (порядок команд не важен). Несколько пар объединяются через OR."""
    clauses, args = [], []
    for pr in pairs or []:
        if not pr or len(pr) < 2:
            continue
        a, b = pr[0], pr[1]
        if not a or not b:
            continue
        clauses.append("((team1 = ? AND team2 = ?) OR (team1 = ? AND team2 = ?))")
        args.extend([a, b, b, a])
    if not clauses:
        return None, []
    return "(%s)" % " OR ".join(clauses), args


def _time_where(col, windows):
    """windows: [["10:00","12:00"], ...] — время суток МСК. Ставка подходит, если
    время суток снимка (`col` формата 'YYYY-MM-DD HH:MM:SS') попадает в любой
    интервал. Поддержка окна через полночь (start > end)."""
    parts, args = [], []
    texpr = f"substr({col}, 12, 5)"   # 'HH:MM' из '....-.. HH:MM:SS'
    for w in windows or []:
        if not w or len(w) < 2:
            continue
        s, e = w[0], w[1]
        if not s or not e:
            continue
        if s <= e:
            parts.append(f"({texpr} >= ? AND {texpr} <= ?)"); args.extend([s, e])
        else:
            parts.append(f"({texpr} >= ? OR {texpr} <= ?)"); args.extend([s, e])
    if not parts:
        return None, []
    return "(%s)" % " OR ".join(parts), args


def _pair_stats(bets, stake):
    """Агрегат по парам без учёта стороны (Баракуды–Скорпионы = одна пара)."""
    agg = {}
    for b in bets:
        key = tuple(sorted([b.get("team1") or "", b.get("team2") or ""]))
        a = agg.setdefault(key, {"n": 0, "wins": 0, "losses": 0, "profit": 0.0})
        a["n"] += 1
        if b["result"] == WIN:
            a["wins"] += 1
        elif b["result"] == LOSE:
            a["losses"] += 1
        a["profit"] += b["profit"]
    out = []
    for (t1, t2), a in agg.items():
        decided = a["wins"] + a["losses"]
        turnover = a["n"] * stake
        out.append({
            "pair": f"{t1} — {t2}", "n": a["n"],
            "wins": a["wins"], "losses": a["losses"],
            "winrate": round(a["wins"] / decided * 100, 1) if decided else 0.0,
            "profit": round(a["profit"], 2),
            "roi": round(a["profit"] / turnover * 100, 1) if turnover else 0.0,
        })
    out.sort(key=lambda x: (-x["n"], -x["profit"]))
    return out


# --- Сбор ставок -------------------------------------------------------------

def _collect_market_bets(source_key, p):
    """Возвращает список ставок (dict) для market/period источника."""
    src = SOURCES[source_key]
    table = src["table"]
    m = market_by_code(source_key, p["market"])
    if not m:
        raise ValueError(f"Неизвестный рынок {p['market']} для {source_key}")
    odds_col, res_col, line_col = m["odds"], m["result"], m.get("line")

    where = [f"{odds_col} IS NOT NULL",
             f"{res_col} IN ('{WIN}','{LOSE}','{PUSH}')"]
    args = []

    # диапазон кф
    if p.get("odds_min") is not None:
        where.append(f"{odds_col} >= ?"); args.append(float(p["odds_min"]))
    if p.get("odds_max") is not None:
        where.append(f"{odds_col} <= ?"); args.append(float(p["odds_max"]))

    # фильтр по линии (только если у рынка есть колонка линии):
    #   форы — выбор конкретных значений (lines IN ...);
    #   тоталы / инд.тоталы — диапазон line_min..line_max.
    if line_col:
        sel_lines = p.get("lines") or []
        if sel_lines:
            where.append(f"{line_col} IN (%s)" % ",".join("?" * len(sel_lines)))
            args.extend(float(x) for x in sel_lines)
        if p.get("line_min") is not None:
            where.append(f"{line_col} >= ?"); args.append(float(p["line_min"]))
        if p.get("line_max") is not None:
            where.append(f"{line_col} <= ?"); args.append(float(p["line_max"]))

    # момент входа: предматч | определённая минута (точно) | перерыв перед периодом N.
    # Среди подходящих снимков берётся ПЕРВЫЙ по времени (см. ROW_NUMBER ниже),
    # поэтому для "break" первый снимок периода N = сразу после перерыва.
    entry = p.get("entry", {}) or {}
    kind = entry.get("kind")
    if kind == "prematch" and src["prematch_where"]:
        where.append(f"({src['prematch_where']})")
    elif kind == "minute" and entry.get("n") is not None:
        where.append("game_minute = ?"); args.append(int(entry["n"]))
    elif kind == "break" and entry.get("n") is not None:
        pc = src["period_col"]
        where.append(f"{pc} = ?"); args.append(int(entry["n"]))

    # лиги
    leagues = p.get("leagues") or []
    if leagues:
        where.append("league IN (%s)" % ",".join("?" * len(leagues)))
        args.extend(leagues)

    # даты
    if p.get("date_from"):
        where.append("date(created_at) >= ?"); args.append(p["date_from"])
    if p.get("date_to"):
        where.append("date(created_at) <= ?"); args.append(p["date_to"])

    # время суток снимка (несколько интервалов МСК) — по snap_dt_msk
    tww, twa = _time_where("snap_dt_msk", p.get("time_windows"))
    if tww:
        where.append(tww); args.extend(twa)

    # пары команд
    pw, pa = _pair_where(p.get("pairs"))
    if pw:
        where.append(pw); args.extend(pa)

    meta = ", ".join(META_COLS)
    line_sel = f", {line_col} AS line_val" if line_col else ", NULL AS line_val"
    sql = f"""
        SELECT {meta}, {odds_col} AS odds_val, {res_col} AS res_val{line_sel}
        FROM (
            SELECT *, ROW_NUMBER() OVER (
                PARTITION BY event_id ORDER BY id ASC
            ) AS rn
            FROM {table}
            WHERE {' AND '.join(where)}
        ) WHERE rn = 1
        ORDER BY id ASC
    """
    con = _connect(source_key)
    rows = con.execute(sql, args).fetchall()
    con.close()

    stake = p.get("stake", 1000.0)
    bets = []
    for r in rows:
        prof = _profit(r["res_val"], r["odds_val"], stake)
        bets.append({
            "event_id": r["event_id"], "league": r["league"],
            "team1": r["team1"], "team2": r["team2"],
            "date": (r["created_at"] or "")[:19],
            "game_minute": r["game_minute"],
            "odds": r["odds_val"], "line": r["line_val"],
            "result": r["res_val"], "final_score": r["final_score"],
            "profit": round(prof, 2),
        })
    return bets


def _collect_signal_bets(source_key, p):
    """Ставки из ipbl.db/signals: проходим по ВСЕМ решённым матчам (дедуп по
    event_id), фильтруя только по «запасу» (2*сумма - линия <= запас) и лигам."""
    con = _connect(source_key)

    # Список лиг: выбранные чекбоксами, иначе все присутствующие в БД.
    all_leagues = [r[0] for r in con.execute(
        "SELECT DISTINCT league FROM signals WHERE league IS NOT NULL")]
    sel = p.get("leagues") or []
    leagues = [lg for lg in all_leagues if lg in sel] if sel else all_leagues

    # Запас по каждой лиге: из параметров, иначе дефолт бота.
    zapas = p.get("zapas") or {}

    where = [f"result IN ('{WIN}','{LOSE}')", "formula_value IS NOT NULL"]
    args = []

    # (лига AND formula_value <= запас_лиги) OR ...  — запас свой у каждой лиги.
    lg_clauses = []
    for lg in leagues:
        z = zapas.get(lg, _default_zapas(lg))
        # запас 0 (или не задан) — фильтр по формуле не применяем, берём все матчи лиги
        if z is None or float(z) == 0:
            lg_clauses.append("league = ?"); args.append(lg)
        else:
            lg_clauses.append("(league = ? AND formula_value <= ?)")
            args.extend([lg, float(z)])
    if lg_clauses:
        where.append("(%s)" % " OR ".join(lg_clauses))
    else:
        where.append("0")  # ни одной лиги — пустой результат

    if p.get("odds_min") is not None:
        where.append("odds >= ?"); args.append(float(p["odds_min"]))
    if p.get("odds_max") is not None:
        where.append("odds <= ?"); args.append(float(p["odds_max"]))
    if p.get("date_from"):
        where.append("date(created_at) >= ?"); args.append(p["date_from"])
    if p.get("date_to"):
        where.append("date(created_at) <= ?"); args.append(p["date_to"])

    # время суток (несколько интервалов МСК) — по created_at сигнала
    tww, twa = _time_where("created_at", p.get("time_windows"))
    if tww:
        where.append(tww); args.extend(twa)

    # пары команд
    pw, pa = _pair_where(p.get("pairs"))
    if pw:
        where.append(pw); args.extend(pa)

    # Дедуп: один сигнал на матч (первый по времени среди подходящих).
    sql = f"""
        SELECT event_id, league, team1, team2, side, line, odds, result,
               final_score, created_at, status, formula_value, half_total
        FROM (
            SELECT *, ROW_NUMBER() OVER (
                PARTITION BY event_id ORDER BY id ASC
            ) AS rn
            FROM signals
            WHERE {' AND '.join(where)}
        ) WHERE rn = 1
        ORDER BY created_at ASC, event_id ASC
    """
    rows = con.execute(sql, args).fetchall()
    con.close()

    stake = p.get("stake", 1000.0)
    bets = []
    for r in rows:
        prof = _profit(r["result"], r["odds"], stake)
        bets.append({
            "event_id": r["event_id"], "league": r["league"],
            "team1": r["team1"], "team2": r["team2"],
            "date": (r["created_at"] or "")[:19],
            "game_minute": None,
            "odds": r["odds"], "line": r["line"], "side": r["side"],
            "result": r["result"], "final_score": r["final_score"],
            "status": r["status"], "zapas": r["formula_value"],
            "profit": round(prof, 2),
        })
    return bets


# --- Метрики и кривая --------------------------------------------------------

def _metrics(bets, stake, bank):
    n = len(bets)
    wins = sum(1 for b in bets if b["result"] == WIN)
    losses = sum(1 for b in bets if b["result"] == LOSE)
    pushes = sum(1 for b in bets if b["result"] == PUSH)
    turnover = n * stake
    profit = sum(b["profit"] for b in bets)
    decided = wins + losses
    avg_odds = (sum(float(b["odds"]) for b in bets) / n) if n else 0.0

    # кумулятивная кривая (по порядку ставок) + просадка + серии +/−
    cum = 0.0
    peak = 0.0
    max_dd = 0.0
    lose_streak = win_streak = 0
    max_lose_streak = max_win_streak = 0
    curve = []
    daily = {}            # день -> кумулятивная эквити (последнее за день)
    daily_profit = {}     # день -> суммарный профит за день
    daily_matches = {}    # день -> множество event_id (кол-во матчей за день)
    weekday = [0.0] * 7   # профит по дням недели (Пн..Вс)
    weekday_matches = [set() for _ in range(7)]  # матчи по дням недели
    for b in bets:
        cum += b["profit"]
        peak = max(peak, cum)
        max_dd = max(max_dd, peak - cum)
        if b["result"] == LOSE:
            lose_streak += 1; win_streak = 0
            max_lose_streak = max(max_lose_streak, lose_streak)
        elif b["result"] == WIN:
            win_streak += 1; lose_streak = 0
            max_win_streak = max(max_win_streak, win_streak)
        day = (b["date"] or "")[:10]
        daily[day] = cum
        daily_profit[day] = daily_profit.get(day, 0.0) + b["profit"]
        daily_matches.setdefault(day, set()).add(b["event_id"])
        if day:
            try:
                wd = datetime.date.fromisoformat(day).weekday()
                weekday[wd] += b["profit"]
                weekday_matches[wd].add(b["event_id"])
            except ValueError:
                pass

    for day in sorted(daily):
        curve.append({"date": day, "cum_profit": round(daily[day], 2),
                      "cum_profit_pct": round(daily[day] / bank * 100, 3) if bank else 0})

    daily_list = [{"date": d, "profit": round(daily_profit[d], 2),
                   "matches": len(daily_matches[d])} for d in sorted(daily_profit)]
    weekday_list = [{"day": WEEKDAYS_RU[i], "profit": round(weekday[i], 2),
                     "matches": len(weekday_matches[i])} for i in range(7)]

    # просадка в днях (по дневной кривой эквити): длина периода ниже прошлого пика
    days_sorted = sorted(daily)
    peak_val = 0.0
    peak_day = None
    max_dd_days = cur_dd_days = 0
    for day in days_sorted:
        try:
            d = datetime.date.fromisoformat(day)
        except ValueError:
            continue
        if peak_day is None:
            peak_day = d
        val = daily[day]
        if val >= peak_val:
            peak_val = val; peak_day = d; cur_dd_days = 0
        else:
            cur_dd_days = (d - peak_day).days
            max_dd_days = max(max_dd_days, cur_dd_days)

    return {
        "bets": n, "matches": len({b["event_id"] for b in bets}),
        "wins": wins, "losses": losses, "pushes": pushes,
        "winrate": round(wins / decided * 100, 2) if decided else 0.0,
        "turnover": round(turnover, 2),
        "profit": round(profit, 2),
        "profit_pct": round(profit / bank * 100, 3) if bank else 0.0,
        "roi": round(profit / turnover * 100, 2) if turnover else 0.0,
        "avg_odds": round(avg_odds, 3),
        "max_drawdown": round(max_dd, 2),
        "max_drawdown_pct": round(max_dd / bank * 100, 3) if bank else 0.0,
        "max_lose_streak": max_lose_streak,
        "max_win_streak": max_win_streak,
        "max_drawdown_days": max_dd_days,
        "current_drawdown_days": cur_dd_days,
        "curve": curve,
        "daily_profit": daily_list,
        "weekday_profit": weekday_list,
    }


def run_backtest(p):
    source_key = p["source"]
    if source_key not in SOURCES:
        raise ValueError(f"Неизвестный источник {source_key}")
    stake = float(p.get("stake", 1000.0))
    bank = float(p.get("bank", 100000.0))
    p["stake"] = stake

    if SOURCES[source_key]["kind"] == "signals":
        bets = _collect_signal_bets(source_key, p)
    else:
        bets = _collect_market_bets(source_key, p)

    metrics = _metrics(bets, stake, bank)
    metrics["stake"] = stake
    metrics["bank"] = bank
    pairs = _pair_stats(bets, stake)
    # таблицу ставок отдаём ограниченно (первые 500), метрики/пары — по всем
    return {"metrics": metrics, "bets": bets[:500], "bets_total": len(bets),
            "pairs": pairs[:500]}
