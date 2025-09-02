from modules.utils import get_event_status_state
from flask import request, session, g
from modules.utils import (
    validate_team_id,
    get_max_users,
    get_static_data,
    get_current_gw,
    init_last_event_updated,
    get_event_status_last_update,
    ordinalformat,
    thousands,
    millions,
    territory_icon,
    get_overall_league_leader_total,
    get_event_status_state
)
from modules.aggregate_data import merge_team_and_global, filter_and_sort_players, sort_table_data
from modules.fetch_mini_leagues import (
    get_league_name,
    get_team_ids_from_league,
    get_team_mini_league_summary,
    append_current_manager,
)
from modules.fetch_teams_table import aggregate_team_stats
from modules.fetch_all_tables import (
    build_player_info,  # Now inside get_static_data
    populate_player_info_all_with_live_data,
)
from modules.fetch_manager_data import get_manager_data, get_manager_history
from flask import (
    Flask,
    g,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    session,
    url_for,
    current_app as app,
)

import sqlite3
import requests
import os
import json
from datetime import datetime, timezone
import copy
import flask
import logging

logging.basicConfig(
    level=logging.INFO,
    # format="%(levelname)-8s %(name)s: %(message)s"
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s"
)


# Create your Flask app
app = Flask(__name__)

# pull from env, default to INFO
log_level_name = os.environ.get("LOG_LEVEL", "INFO").upper()
level = getattr(logging, log_level_name, logging.INFO)

logging.basicConfig(
    level=level,
    format="%(levelname)-8s %(name)s: %(message)s",
    # format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)

# root logger (so your modules inherit this)
logging.getLogger().setLevel(level)
logging.getLogger('werkzeug').setLevel(level)
app.logger.setLevel(level)

# alias for convenience
logger = app.logger

# Also make the built-in Werkzeug request-logger DEBUG
logging.getLogger('werkzeug').setLevel(logging.DEBUG)


# ... your routes, blueprints, etc. go here ...

FPL_API = "https://fantasy.premierleague.com/api"
HEADERS = {"User-Agent": "Mozilla/5.0"}

# app.secret_key = os.urandom(24)  # For deployment
app.secret_key = os.environ.get(
    "FLASK_SECRET", "dev-secret-for-local")  # Development only
app.config["TEMPLATES_AUTO_RELOAD"] = True


# Jinja filters
app.jinja_env.filters["ordinalformat"] = ordinalformat
app.jinja_env.filters["thousands"] = thousands
app.jinja_env.filters["millions"] = millions
app.jinja_env.filters["territory_icon"] = territory_icon

DATABASE = "page_views.db"

# Initialize the fallback timestamp before any requests
init_last_event_updated()


logger = logging.getLogger(__name__)


@app.before_request
def load_manager_into_g():
    """
    1) Clear session team_id when returning to index (GET /).
    2) Prefer team_id from the URL; otherwise fall back to session.
    3) Attach event-status snapshot to g (gw/is_live/last_update).
    4) Load manager once per request and memoize on g to avoid re-fetch.
    """
    # Ignore static assets
    if request.endpoint == "static":
        return

    # Step 1: clear team on index GET
    if request.endpoint == "index" and request.method == "GET":
        session.pop("team_id", None)
        logger.info("Cleared session team_id on GET to index route")

    # Step 2: resolve team_id (URL > session)
    url_tid = (request.view_args or {}).get("team_id")
    if url_tid is not None:
        session["team_id"] = url_tid
        logger.debug("Session team_id set to %s", url_tid)

    tid = url_tid if url_tid is not None else session.get("team_id")
    g.team_id = tid

    # Step 3: event-status snapshot (cheap; utils caches)
    # {"gw": int, "is_live": bool, "last_update": datetime}
    st = get_event_status_state()
    g.current_gw = st["gw"]
    g.is_live = st["is_live"]
    g.event_last_update = st["last_update"]
    logger.debug("[initialize_session] gw=%s live=%s last=%s",
                 g.current_gw, g.is_live, g.event_last_update)

    # Step 4: load manager once per request, memoized on g
    g.manager = None
    if tid:
        cache = g.__dict__.setdefault("_mgr_cache", {})
        if tid not in cache:
            try:
                # <- inside should use SESSION/get_json_cached now
                m = get_manager_data(tid)
                m = m or {}
                m["id"] = tid
                cache[tid] = m
            except Exception as e:
                logger.error("Failed to load manager %s: %s", tid, e)
                cache[tid] = {"id": tid, "first_name": "Unknown",
                              "team_name": f"Manager {tid}"}
        g.manager = cache[tid]


@app.context_processor
def inject_manager():
    """
    Makes `manager` and `team_id` available to all templates via Jinja.
    Uses g.manager set in before_request.
    """
    if not getattr(g, "manager", None):
        return {}

    return {
        "team_id": g.manager["id"],
        "manager": g.manager
    }


# Go to this URL to reset session
@app.route('/reset-session')
def reset_session():
    session.clear()
    return "Session cleared!"


@app.before_request
def initialize_session():
    if request.endpoint == "static":
        return
    es = get_event_status_state()             # ← single source of truth
    g.current_gw = es["gw"]
    g.is_live = es["is_live"]
    g.event_last_update = es["last_update"]
    session["current_gw"] = g.current_gw      # optional convenience
    app.logger.debug("[initialize_session] gw=%s live=%s last=%s",
                     g.current_gw, g.is_live, g.event_last_update)


@app.route("/debug/gw")
def debug_gw():
    from flask import jsonify
    return jsonify(current_gw=g.current_gw, session_gw=session.get("current_gw"))


# --- Flash preseason ---


def flash_if_preseason():
    if session.get("current_gw") is None:
        flash('Season not started. No team-specific data yet. "Player Totals" data are from last season.', "info")


# --- INDEX ---


@app.route("/", methods=["GET", "POST"])
def index():
    MAX_USERS = get_max_users()
    current_gw = session.get('current_gw', '__')
    # GET
    if request.method == "GET":
        # session.pop("team_id", None)
        return render_template("index.html",
                               max_users=MAX_USERS,
                               current_gw=current_gw)
    # POST
    team_id = validate_team_id(request.form.get("team_id"), MAX_USERS)
    if team_id is None:
        return render_template("index.html",
                               max_users=MAX_USERS,
                               current_gw=current_gw)
    session['team_id'] = team_id
    return redirect(url_for("summary", team_id=team_id))

# --- ABOUT ---


@app.route("/about")
def about():
    return render_template("about.html",
                           current_gw=session.get('current_gw'))

# --- Manager ---


@app.route("/<int:team_id>/team/manager")
def manager(team_id):
    try:
        manager_history = get_manager_history(team_id)

        # logger.info(json.dumps(g.manager, indent=2))
        m = g.manager
        logger.info(
            f"{m['id']} - {m['first_name']} {m['last_name']} - {m['team_name']} - {m['country_code']}")

        return render_template(
            "manager.html",
            team_id=team_id,
            current_gw=session.get('current_gw'),
            manager=g.manager,
            chips_state=manager_history["chips_state"],
            history=manager_history["history"],
            current_rows=manager_history["current_rows"],
            current_page='manager'
        )

    except Exception as e:
        flash(f"Error: {e}", "error")
        return redirect(url_for("index"))


# --- SUMMARY PAGE ---


@app.route("/<int:team_id>/team/summary")
def summary(team_id):
    # flash_if_preseason()
    return render_template("summary.html",
                           team_id=team_id,
                           current_gw=session.get('current_gw'),
                           manager=g.manager,
                           sort_by=request.args.get(
                               'sort_by', 'total_points_team'),
                           order=request.args.get('order', 'desc'),
                           current_page='summary')

# --- DEFENCE PAGE ---


@app.route("/<int:team_id>/team/defence")
def defence(team_id):
    return render_template("defence.html",
                           team_id=team_id,
                           current_gw=session.get('current_gw'),
                           manager=g.manager,
                           sort_by=request.args.get(
                               'sort_by', 'defensive_contribution_team'),
                           order=request.args.get('order', 'desc'),
                           current_page='defence')


@app.route("/<int:team_id>/team/offence")
def offence(team_id):
    # flash_if_preseason()
    return render_template("offence.html",
                           team_id=team_id,
                           current_gw=session.get('current_gw'),
                           manager=g.manager,
                           sort_by=request.args.get(
                               'sort_by', 'goals_assists_team'),
                           order=request.args.get('order', 'desc'),
                           current_page='offence')

# --- POINTS PAGE ---


@app.route("/<int:team_id>/team/points")
def points(team_id):
    return render_template("points.html",
                           team_id=team_id,
                           current_gw=session.get('current_gw'),
                           manager=g.manager,
                           sort_by=request.args.get(
                               'sort_by', 'total_points_team'),
                           order=request.args.get('order', 'desc'),
                           current_page='points')


# --- TEAMS PAGE ---


@app.route("/<int:team_id>/team/teams")
def teams(team_id):

    try:
        # grab current GW from session
        current_gw = session.get('current_gw', '__')

        # default sort key + order
        default_sort_by = 'goals_scored'
        default_order = 'desc'

        # allow user to override via query-string
        sort_by = request.args.get('sort_by', default_sort_by)
        order = request.args.get('order',   default_order)

        # render your teams.html — manager is injected by your context‐processor,
        # and tableType='teams' will drive the AJAX into the aggregate_team_stats branch
        return render_template(
            "teams.html",
            team_id=team_id,
            current_gw=current_gw,
            manager=g.manager,
            sort_by=sort_by,
            order=order,
            current_page='teams'
        )

    except ValueError:
        flash("Team ID must be a valid number", "error")
    except Exception as e:
        flash(f"Error loading Teams page: {e}", "error")

    return redirect(url_for("index"))

# --- TALISMAN PAGE ---


@app.route("/<int:team_id>/team/talisman")
def talisman(team_id):
    return render_template("talisman.html",
                           team_id=team_id,
                           current_gw=session.get('current_gw'),
                           manager=g.manager,
                           sort_by=request.args.get('sort_by', 'total_points'),
                           order=request.args.get('order', 'desc'),
                           current_page='talisman')

# --- MINI LEAGUES PAGE ---


@app.route("/<int:league_id>/leagues/mini_leagues")
def mini_leagues(league_id):

    # 1️⃣ ensure we know the current GW
    current_gw = session.get("current_gw") or get_current_gw()
    session["current_gw"] = current_gw

    # 2️⃣ pull sort params out of the query (for JS to re‐use)
    sort_by = request.args.get("sort_by", "rank")
    order = request.args.get("order",   "asc")

    league_name = get_league_name(league_id)

    # set your default rows-per-page here
    default_page_size = 10

    # 3️⃣ just render the template—no DB or API calls here
    return render_template(
        "mini_leagues.html",
        team_id=session.get("team_id"),
        league_id=league_id,
        current_gw=current_gw,
        sort_by=sort_by,
        order=order,
        league_name=league_name,
        current_page="mini_leagues",
        maxShow=default_page_size,
    )


@app.route("/get-sorted-players")
def get_sorted_players():
    app.logger.debug(
        "Received minutes filter: %s–%s",
        request.args.get("min_minutes"),
        request.args.get("max_minutes"),
    )

    # 1) Parse query params
    table = request.args.get("table", default="goals")
    team_id = request.args.get("team_id", type=int)
    league_id = request.args.get("league_id", type=int)
    sort_by = request.args.get("sort_by", default=None)
    order = request.args.get("order", default="desc")
    max_show = request.args.get("max_show", 2, type=int)
    current_gw = g.current_gw
    static_data = None  # lazy-loaded only when needed

    app.logger.debug("current_gw=%s", current_gw)

    # 2) Validate required params
    if table == "mini_league" and league_id is None:
        return jsonify({"error": "Missing league_id"}), 400
    if table != "mini_league" and team_id is None:
        return jsonify({"error": "Missing team_id"}), 400

    # 3) FAST PATH: use cached static_player_info for current GW (refresh only if stale)
    conn = sqlite3.connect(DATABASE, check_same_thread=False)
    cur = conn.cursor()

    cur.execute(
        "SELECT data, last_fetched FROM static_player_info WHERE gameweek = ?",
        (current_gw,)
    )
    row = cur.fetchone()

    def _load_static_blob(r):
        data_str, _last = r
        return {int(pid): blob for pid, blob in json.loads(data_str).items()}

    if row:
        static_blob = _load_static_blob(row)
        if g.event_last_update and datetime.fromisoformat(row[1]) < g.event_last_update:
            app.logger.debug("static_player_info stale → refreshing")
            static_data = static_data or get_static_data(
                current_gw=current_gw,
                event_updated_iso=(g.event_last_update.isoformat()
                                   if g.event_last_update else None)
            )

            cur.execute(
                "SELECT data, last_fetched FROM static_player_info WHERE gameweek = ?",
                (current_gw,)
            )
            row = cur.fetchone()
            static_blob = _load_static_blob(row)
    else:
        app.logger.debug("no static_player_info row → fetching")
        static_data = static_data or get_static_data(
            current_gw=current_gw,
            event_updated_iso=(g.event_last_update.isoformat()
                               if g.event_last_update else None)
        )

        cur.execute(
            "SELECT data, last_fetched FROM static_player_info WHERE gameweek = ?",
            (current_gw,)
        )
        row = cur.fetchone()
        static_blob = _load_static_blob(row)

    # 4) Mini-league branch (no team_blob)
    if table == "mini_league":
        cur.execute("""
            SELECT data, last_fetched FROM mini_league_cache
            WHERE league_id=? AND gameweek=? AND team_id=? AND max_show=?
        """, (league_id, current_gw, team_id, max_show))
        row = cur.fetchone()
        if row:
            data, last_fetched = row
            if not g.event_last_update or datetime.fromisoformat(last_fetched) >= g.event_last_update:
                players = json.loads(data)
                players.sort(key=lambda o: o.get(sort_by, 0),
                             reverse=(order == "desc"))
                conn.close()
                return jsonify(players=players, manager=g.manager)

        managers = get_team_ids_from_league(league_id, max_show)
        append_current_manager(managers, team_id, league_id, logger=app.logger)

        static_data = static_data or get_static_data(
            current_gw=current_gw,
            event_updated_iso=(g.event_last_update.isoformat()
                               if g.event_last_update else None)
        )

        players = []
        for m in managers:
            summary = get_team_mini_league_summary(m["entry"], static_data)
            summary.update({"team_id": m["entry"], **m})
            players.append(summary)

        players.sort(key=lambda o: o.get(sort_by, 0),
                     reverse=(order == "desc"))

        league_leader_pts = max((p.get("total_points", 0)
                                for p in players), default=0)
        leader_pts = get_overall_league_leader_total()
        for p in players:
            p["pts_behind_league_leader"] = p.get(
                "total_points", 0) - league_leader_pts
            p["pts_behind_overall"] = p.get(
                "total_points", 0) - (leader_pts or 0)
            p["years_active_label"] = ordinalformat(p.get("years_active", 0))

        cur.execute("""
            INSERT OR REPLACE INTO mini_league_cache
            (league_id, gameweek, team_id, max_show, data, last_fetched)
            VALUES (?,?,?,?,?,?)
        """, (league_id, current_gw, team_id, max_show,
              json.dumps(players), datetime.now(timezone.utc).isoformat()))
        conn.commit()
        conn.close()
        return jsonify(players=players, manager=g.manager)

    # 5) Load or refresh team_player_info (merge needs this)
    cur.execute("SELECT COUNT(*) FROM team_player_info WHERE team_id=? AND gameweek=?",
                (team_id, current_gw))
    count_tg = cur.fetchone()[0]
    app.logger.debug("Rows for team_id=%s, gw=%s: %s",
                     team_id, current_gw, count_tg)

    cur.execute(
        "SELECT data, last_fetched FROM team_player_info WHERE team_id=? AND gameweek=?",
        (team_id, current_gw)
    )
    row = cur.fetchone()

    if row:
        app.logger.debug(
            "Found existing team_player_info for team_id=%s, gw=%s", team_id, current_gw)
        data, last_fetched = row
        app.logger.debug("last_fetched=%s, event_status_last_update=%s",
                         last_fetched, g.event_last_update)
        if not g.event_last_update or datetime.fromisoformat(last_fetched) >= g.event_last_update:
            app.logger.debug("Using cached team_player_info")
            team_blob = {int(pid): blob for pid,
                         blob in json.loads(data).items()}
        else:
            app.logger.debug(
                "Cached team_player_info stale → refreshing from live")
            static_data = static_data or get_static_data(
                current_gw=current_gw,
                event_updated_iso=(g.event_last_update.isoformat()
                                   if g.event_last_update else None)
            )

            team_blob = populate_player_info_all_with_live_data(
                team_id, static_blob, static_data)
            app.logger.debug("Refreshed team_blob keys=%s",
                             list(team_blob.keys()))
            cur.execute(
                """INSERT OR REPLACE INTO team_player_info
                   (team_id, gameweek, data, last_fetched)
                   VALUES (?, ?, ?, ?)""",
                (team_id, current_gw, json.dumps(team_blob),
                 datetime.now(timezone.utc).isoformat())
            )
            conn.commit()
    else:
        app.logger.debug(
            "No team_player_info row → fetching fresh for team_id=%s, gw=%s", team_id, current_gw)
        static_data = static_data or get_static_data(
            current_gw=current_gw,
            event_updated_iso=(g.event_last_update.isoformat()
                               if g.event_last_update else None)
        )

        team_blob = populate_player_info_all_with_live_data(
            team_id, static_blob, static_data)
        app.logger.debug("Fresh team_blob keys=%s", list(team_blob.keys()))
        cur.execute(
            """INSERT OR REPLACE INTO team_player_info
               (team_id, gameweek, data, last_fetched)
               VALUES (?, ?, ?, ?)""",
            (team_id, current_gw, json.dumps(team_blob),
             datetime.now(timezone.utc).isoformat())
        )
        conn.commit()

    app.logger.debug("Final team_blob length=%s", len(team_blob))
    conn.close()

    # 6) Special tables
    if table == "talisman":
        app.logger.debug("Talisman table")
        players, _, is_truncated, price_range = filter_and_sort_players(
            static_blob, {}, request.args)
        seen, talisman_list = set(), []
        for p in players:
            if p["team_code"] not in seen:
                seen.add(p["team_code"])
                talisman_list.append(p)
        images = [{"photo": p["photo"], "team_code": p["team_code"]}
                  for p in talisman_list[:5]]
        return jsonify(players=talisman_list, players_images=images, is_truncated=False,
                       manager=g.manager, price_range=price_range)

    if table == "teams":
        app.logger.debug("Teams table")
        merged = merge_team_and_global(static_blob, team_blob)
        stats = aggregate_team_stats(merged)
        sorted_stats = sorted(
            (team for team in stats.values() if team.get(sort_by, 0) != 0),
            key=lambda team: team.get(sort_by, 0),
            reverse=(order == "desc"),
        )
        top5, seen = [], set()
        for club in sorted_stats:
            if club["team_code"] not in seen:
                seen.add(club["team_code"])
                top5.append(
                    {"team_code": club["team_code"], "team_name": club["team_name"]})
                if len(top5) == 5:
                    break
        return jsonify(players=sorted_stats, players_images=top5, manager=g.manager)

    # 7) Default tables (summary, defence, offence, points)
    app.logger.info("GW=%s, mins=%s–%s", g.current_gw,
                    request.args.get("min_minutes"), request.args.get("max_minutes"))

    players, images, is_truncated, price_range = filter_and_sort_players(
        static_blob, team_blob, request.args)
    return jsonify(players=players, players_images=images, is_truncated=is_truncated,
                   manager=g.manager, price_range=price_range)


if __name__ == "__main__":
    debug_flag = os.environ.get("FLASK_DEBUG", "0") in ("1", "true", "True")
    app.run(debug=debug_flag)

# LOG_LEVEL=DEBUG python3 app.py
# LOG_LEVEL=INFO python3 app.py

# In the terminal:
# export FLASK_ENV=development
# export FLASK_DEBUG=1
# flask run

# grep -r "print(" modules/
# That will find all the print() calls inside your modules / directory (or wherever your app lives).
