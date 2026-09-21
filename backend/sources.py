"""
Декларативное описание всех источников данных (8 БД) для движка бэктеста.

Три типа таблиц:
  - market   : market_snapshots, поминутные снимки рынков (баскетбол Pro/Prime, хоккей)
  - period   : period_snapshots, снимки по четвертям (баскетбол Pro)
  - signals  : ipbl.db/signals, готовые сигналы стратегии ТМ (особый адаптер)

Каждый рынок (исход) описан парой колонок: котировка (odds) + результат (r_*).
Результат в БД: 'Выигрыш' / 'Проигрыш' / 'Возврат' / NULL (ещё не резолвнут).
"""

# --- Наборы рынков (исходов) -------------------------------------------------

# Базовые рынки баскетбола (есть во всех market/period БД)
BASKET_MARKETS = [
    {"code": "TB",    "label": "ТБ (тотал больше)", "odds": "total_b_odds", "result": "r_total_b", "line": "total_line", "group": "Тотал"},
    {"code": "TM",    "label": "ТМ (тотал меньше)", "odds": "total_m_odds", "result": "r_total_m", "line": "total_line", "group": "Тотал"},
    {"code": "F1",    "label": "Фора 1",            "odds": "fora1_odds",   "result": "r_fora1",   "line": "fora_line",  "group": "Фора"},
    {"code": "F2",    "label": "Фора 2",            "odds": "fora2_odds",   "result": "r_fora2",   "line": "fora_line",  "group": "Фора"},
    {"code": "IT1B",  "label": "Инд. тотал 1 Б",    "odds": "it1_b_odds",   "result": "r_it1_b",   "line": "it1_line",   "group": "Инд. тотал 1"},
    {"code": "IT1M",  "label": "Инд. тотал 1 М",    "odds": "it1_m_odds",   "result": "r_it1_m",   "line": "it1_line",   "group": "Инд. тотал 1"},
    {"code": "IT2B",  "label": "Инд. тотал 2 Б",    "odds": "it2_b_odds",   "result": "r_it2_b",   "line": "it2_line",   "group": "Инд. тотал 2"},
    {"code": "IT2M",  "label": "Инд. тотал 2 М",    "odds": "it2_m_odds",   "result": "r_it2_m",   "line": "it2_line",   "group": "Инд. тотал 2"},
    {"code": "W1",    "label": "П1",                "odds": "win1_odds",    "result": "r_win1",    "line": None,         "group": "Исход"},
    {"code": "W2",    "label": "П2",                "odds": "win2_odds",    "result": "r_win2",    "line": None,         "group": "Исход"},
]

# Ничья по четверти (только period-БД)
PERIOD_EXTRA = [
    {"code": "WX", "label": "Ничья (X)", "odds": "winx_odds", "result": "r_winx", "line": None, "group": "Исход"},
]

# Рынки CAGE Division. Тоталы и инд. тоталы берутся из ДОЧЕРНЕЙ таблицы
# total_lines (у CAGE собраны ВСЕ линии), поэтому помечены ключом "tl_kind" и
# ссылаются на колонки total_lines (b_odds/m_odds/r_b/r_m). Форы и исходы —
# плоские колонки market_snapshots, как у остальных баскетбольных БД.
# UI-ключ линии (total_line/it1_line/it2_line) переиспользует те же имена, что
# у Pro/Prime — фронт покажет тот же фильтр «Линия от/до».
CAGE_MARKETS = [
    {"code": "TB",    "label": "ТБ (тотал больше)", "odds": "b_odds",     "result": "r_b",     "line": "total_line", "group": "Тотал",        "tl_kind": "total"},
    {"code": "TM",    "label": "ТМ (тотал меньше)", "odds": "m_odds",     "result": "r_m",     "line": "total_line", "group": "Тотал",        "tl_kind": "total"},
    {"code": "F1",    "label": "Фора 1",            "odds": "fora1_odds", "result": "r_fora1", "line": "fora_line",  "group": "Фора"},
    {"code": "F2",    "label": "Фора 2",            "odds": "fora2_odds", "result": "r_fora2", "line": "fora_line",  "group": "Фора"},
    {"code": "IT1B",  "label": "Инд. тотал 1 Б",    "odds": "b_odds",     "result": "r_b",     "line": "it1_line",   "group": "Инд. тотал 1", "tl_kind": "it1"},
    {"code": "IT1M",  "label": "Инд. тотал 1 М",    "odds": "m_odds",     "result": "r_m",     "line": "it1_line",   "group": "Инд. тотал 1", "tl_kind": "it1"},
    {"code": "IT2B",  "label": "Инд. тотал 2 Б",    "odds": "b_odds",     "result": "r_b",     "line": "it2_line",   "group": "Инд. тотал 2", "tl_kind": "it2"},
    {"code": "IT2M",  "label": "Инд. тотал 2 М",    "odds": "m_odds",     "result": "r_m",     "line": "it2_line",   "group": "Инд. тотал 2", "tl_kind": "it2"},
    {"code": "W1",    "label": "П1",                "odds": "win1_odds",  "result": "r_win1",  "line": None,         "group": "Исход"},
    {"code": "W2",    "label": "П2",                "odds": "win2_odds",  "result": "r_win2",  "line": None,         "group": "Исход"},
]

# Хоккейные доп. рынки (1X2 + двойные шансы)
HOCKEY_EXTRA = [
    {"code": "HX",  "label": "Ничья (X)",   "odds": "draw_odds",   "result": "r_draw", "line": None, "group": "Исход"},
    {"code": "DC1X","label": "1X (дв. шанс)","odds": "dc_1x_odds",  "result": "r_1x",   "line": None, "group": "Двойной шанс"},
    {"code": "DC12","label": "12 (дв. шанс)","odds": "dc_12_odds",  "result": "r_12",   "line": None, "group": "Двойной шанс"},
    {"code": "DCX2","label": "X2 (дв. шанс)","odds": "dc_x2_odds",  "result": "r_x2",   "line": None, "group": "Двойной шанс"},
]

# --- Моменты входа -----------------------------------------------------------
# kind: 'prematch' | 'minute' | 'period'
# Для 'prematch' способ определения снимка задаётся в источнике (prematch_where).


def _basket_entry_points():
    return [
        {"kind": "prematch", "label": "Предматч"},
        {"kind": "minute",   "label": "Определённая минута игры"},
        {"kind": "break",    "label": "Перерыв между четвертями", "values": [2, 3, 4], "col": "quarter"},
    ]


def _hockey_entry_points():
    return [
        {"kind": "prematch", "label": "Предматч"},
        {"kind": "minute",   "label": "Определённая минута игры"},
        {"kind": "break",    "label": "Перерыв между периодами", "values": [2, 3], "col": "period"},
    ]


def _period_entry_points():
    # «По четвертям»: quarter = номер рынка тотала четверти (перерыв перед четвертью),
    # либо вход на конкретной игровой минуте.
    return [
        {"kind": "break",  "label": "Четверть (тотал N-й четверти)", "values": [1, 2, 3], "col": "quarter"},
        {"kind": "minute", "label": "Определённая минута игры"},
    ]


# --- Источники ---------------------------------------------------------------

SOURCES = {
    "pro": {
        "label": "Pro (муж)", "db": "pro_markets.db", "table": "market_snapshots",
        "kind": "market", "period_col": "quarter", "prematch_where": "game_minute = 0",
        "markets": BASKET_MARKETS, "entry_points": _basket_entry_points(),
    },
    "prime": {
        "label": "Prime (муж)", "db": "prime_markets.db", "table": "market_snapshots",
        "kind": "market", "period_col": "quarter", "prematch_where": "game_minute = 0",
        "markets": BASKET_MARKETS, "entry_points": _basket_entry_points(),
    },
    "pro_women": {
        "label": "Pro (жен)", "db": "pro_women_markets.db", "table": "market_snapshots",
        "kind": "market", "period_col": "quarter", "prematch_where": "game_minute = 0",
        "markets": BASKET_MARKETS, "entry_points": _basket_entry_points(),
    },
    "prime_women": {
        "label": "Prime (жен)", "db": "prime_women_markets.db", "table": "market_snapshots",
        "kind": "market", "period_col": "quarter", "prematch_where": "game_minute = 0",
        "markets": BASKET_MARKETS, "entry_points": _basket_entry_points(),
    },
    "shorthockey": {
        "label": "Шорт-хоккей", "db": "shorthockey_markets.db", "table": "market_snapshots",
        "kind": "market", "period_col": "period", "prematch_where": "is_prematch = 1",
        "markets": BASKET_MARKETS + HOCKEY_EXTRA, "entry_points": _hockey_entry_points(),
    },
    "pro_periods": {
        "label": "Pro по четвертям (муж)", "db": "pro_periods.db", "table": "period_snapshots",
        "kind": "period", "period_col": "quarter", "prematch_where": None,
        "markets": BASKET_MARKETS + PERIOD_EXTRA, "entry_points": _period_entry_points(),
    },
    "pro_women_periods": {
        "label": "Pro по четвертям (жен)", "db": "pro_women_periods.db", "table": "period_snapshots",
        "kind": "period", "period_col": "quarter", "prematch_where": None,
        "markets": BASKET_MARKETS + PERIOD_EXTRA, "entry_points": _period_entry_points(),
    },
    "cage": {
        "label": "CAGE Division", "db": "cage_markets.db", "table": "market_snapshots",
        "kind": "market", "period_col": "quarter", "prematch_where": "is_prematch = 1",
        "markets": CAGE_MARKETS, "entry_points": _basket_entry_points(),
    },
    "signals": {
        "label": "Сигналы ТМ (ipbl)", "db": "ipbl.db", "table": "signals",
        "kind": "signals", "period_col": None, "prematch_where": None,
        "markets": [], "entry_points": [],
    },
}

# Метаданные снимка, которые тянем для таблицы ставок
META_COLS = ["event_id", "league", "team1", "team2", "snap_dt_msk",
             "game_minute", "score1", "score2", "final_score", "final_total", "created_at"]


def market_by_code(source_key, code):
    for m in SOURCES[source_key]["markets"]:
        if m["code"] == code:
            return m
    return None
