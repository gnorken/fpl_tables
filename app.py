import os
import json
import copy
import logging
import sqlite3
import requests

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

from modules.fetch_manager_data import get_manager_data, get_manager_history
from modules.fetch_all_tables import (
    build_player_info,
    populate_player_info_all_with_live_data,
)
from modules.fetch_teams_table import aggregate_team_stats
from modules.fetch_mini_leagues import (
    get_league_name,
    get_team_ids_from_league,
    get_team_mini_league_summary,
    append_current_manager,
)
from modules.aggregate_data import filter_and_sort_players, sort_table_data
from modules.utils import (
    validate_team_id,
    get_max_users,
    get_static_data,
    get_current_gw,
    ordinalformat,
    thousands,
    millions,
    territory_icon,
    get_overall_league_leader_total,
    performance_emoji,
)

FPL_API = "https://fantasy.premierleague.com/api"
HEADERS = {"User-Agent": "Mozilla/5.0"}

app = Flask(__name__)
app.logger.setLevel(logging.DEBUG)
# app.secret_key = os.urandom(24)  # For deployment
app.secret_key = os.environ.get(
    "FLASK_SECRET", "dev-secret-for-local")  # Development only
app.config["TEMPLATES_AUTO_RELOAD"] = True


# Jinja filters
app.jinja_env.filters["ordinalformat"] = ordinalformat
app.jinja_env.filters["thousands"] = thousands
app.jinja_env.filters["millions"] = millions
app.jinja_env.filters["territory_icon"] = territory_icon
app.jinja_env.filters["performance_emoji"] = performance_emoji

DATABASE = "page_views.db"


@app.before_request
def load_manager_into_g():
    # 1) try path param
    tid = (request.view_args or {}).get("team_id")
    # 2) else fall back to whatever’s in session
    if tid is None:
        tid = session.get("team_id")

    if tid:
        m = get_manager_data(tid)
        m["id"] = tid
        g.manager = m
    else:
        g.manager = None


@app.context_processor
def inject_manager():
    # 1) Try URL param
    tid = (request.view_args or {}).get("team_id")
    # 2) Otherwise fall back to session
    if not tid:
        tid = session.get("team_id")
    if not tid:
        return {}
    m = get_manager_data(tid)
    m["id"] = tid
    return {
        "team_id": tid,
        "manager": m
    }


# Ensure current_gw in session


@app.before_request
def initialize_session():
    if 'current_gw' not in session or session['current_gw'] is None:
        gw = get_current_gw()
        if gw is None:
            session['current_gw'] = None
        else:
            session['current_gw'] = gw

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
        session.pop("team_id", None)
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
    return redirect(url_for("manager", team_id=team_id))

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

        # print(json.dumps(g.manager, indent=2))
        m = g.manager
        print(
            f"{m['id']} - {m['first_name']} {m['last_name']} - {m['team_name']} - {m['country_code']}")

        return render_template(
            "manager.html",
            team_id=team_id,
            current_gw=session.get('current_gw'),
            manager=g.manager,
            chips_state=manager_history["chips_state"],
            history=manager_history["history"],
            current_page='manager'
        )

    except Exception as e:
        flash(f"Error: {e}", "error")
        return redirect(url_for("index"))

# AJAX routes for table and graphs in manager.html


@app.route("/api/current-season")
def current_season():
    sort_by = request.args.get('sort_by', 'gw')
    order = request.args.get('order',   'desc')

    # data = fetch_from_cache_or_api() Implement later
    # mock data
    data = [
        {"gw": 1, "or": 179512, "#:": "▲", "op": 44, "gwr": 3061510, "gwp": 76,
         "pb": 5, "tm": 1, "tc": "4", "£": 100},
        {"gw": 2, "or": 227258, "#:": "▲", "op": 105, "gwr": 3012510, "gwp": 52,
         "pb": 0, "tm": 1, "tc": "4", "£": 100.2},
        {"gw": 3, "or": 137366, "#:": "▼", "op": 49, "gwr": 3456322, "gwp": 50,
         "pb": 3, "tm": 0, "tc": "4", "£": 100.1},
        {"gw": 4, "or": 934653, "#:": "▲", "op": 83, "gwr": 4009234, "gwp": 76,
         "pb": 5, "tm": 1, "tc": "16", "£": 100},
        {"gw": 5, "or": 328543, "#:": "▲", "op": 47, "gwr": 4566213, "gwp": 42,
         "pb": 0, "tm": 1, "tc": "0", "£": 100.2},
        {"gw": 6, "or": 238234, "#:": "▼", "op": 98, "gwr": 82508, "gwp": 60,
         "pb": 3, "tm": 0, "tc": "4", "£": 100.1},
        {"gw": 7, "or": 79412, "#:": "▲", "op": 44, "gwr": 3061510, "gwp": 76,
         "pb": 5, "tm": 1, "tc": "4", "£": 100},
        {"gw": 8, "or": 27258, "#:": "▲", "op": 105, "gwr": 3012510, "gwp": 52,
         "pb": 0, "tm": 1, "tc": "4", "£": 100.2},
        {"gw": 9, "or": 167366, "#:": "▼", "op": 49, "gwr": 3456322, "gwp": 50,
         "pb": 3, "tm": 0, "tc": "4", "£": 100.1},
        {"gw": 10, "or": 492453, "#:": "▲", "op": 83, "gwr": 4009234, "gwp": 76,
         "pb": 5, "tm": 1, "tc": "16", "£": 100},
        {"gw": 11, "or": 438543, "#:": "▲", "op": 47, "gwr": 4566213, "gwp": 42,
         "pb": 0, "tm": 1, "tc": "0", "£": 100.2},
        {"gw": 12, "or": 238234, "#:": "▼", "op": 98, "gwr": 10000000, "gwp": 60,
         "pb": 3, "tm": 0, "tc": "4", "£": 100.1},
        {"gw": 13, "or": 79512, "#:": "▲", "op": 44, "gwr": 3061510, "gwp": 76,
         "pb": 5, "tm": 1, "tc": "4", "£": 100},
        {"gw": 14, "or": 227258, "#:": "▲", "op": 105, "gwr": 312510, "gwp": 52,
         "pb": 0, "tm": 1, "tc": "4", "£": 100.2},
        {"gw": 15, "or": 167366, "#:": "▼", "op": 49, "gwr": 56322, "gwp": 50,
         "pb": 3, "tm": 0, "tc": "4", "£": 100.1},
        {"gw": 16, "or": 424653, "#:": "▲", "op": 83, "gwr": 499234, "gwp": 76,
         "pb": 5, "tm": 1, "tc": "16", "£": 100},
        {"gw": 17, "or": 398543, "#:": "▲", "op": 47, "gwr": 4466213, "gwp": 42,
         "pb": 0, "tm": 1, "tc": "0", "£": 100.2},
        {"gw": 18, "or": 238234, "#:": "▼", "op": 98, "gwr": 102300, "gwp": 90,
         "pb": 3, "tm": 0, "tc": "4", "£": 100.1},
        {"gw": 19, "or": 238234, "#:": "▼", "op": 98, "gwr": 7834000, "gwp": 60,
         "pb": 3, "tm": 0, "tc": "4", "£": 100.1},
        {"gw": 20, "or": 79512, "#:": "▲", "op": 44, "gwr": 3061510, "gwp": 76,
         "pb": 5, "tm": 1, "tc": "4", "£": 100},
        {"gw": 21, "or": 227258, "#:": "▲", "op": 105, "gwr": 322510, "gwp": 52,
         "pb": 0, "tm": 1, "tc": "4", "£": 100.2},
        {"gw": 22, "or": 167366, "#:": "▼", "op": 49, "gwr": 296322, "gwp": 50,
         "pb": 3, "tm": 0, "tc": "4", "£": 100.1},
        {"gw": 23, "or": 167366, "#:": "▼", "op": 49, "gwr": 3456322, "gwp": 40,
         "pb": 3, "tm": 0, "tc": "4", "£": 100.1},
        {"gw": 24, "or": 222653, "#:": "▲", "op": 83, "gwr": 4009234, "gwp": 76,
         "pb": 5, "tm": 1, "tc": "16", "£": 100},
        {"gw": 25, "or": 298543, "#:": "▲", "op": 47, "gwr": 4566213, "gwp": 42,
         "pb": 0, "tm": 1, "tc": "0", "£": 100.2},
        {"gw": 26, "or": 228234, "#:": "▼", "op": 98, "gwr": 82508, "gwp": 20,
         "pb": 3, "tm": 0, "tc": "4", "£": 100.1},
        {"gw": 27, "or": 79512, "#:": "▲", "op": 44, "gwr": 361510, "gwp": 76,
         "pb": 5, "tm": 1, "tc": "4", "£": 100},
        {"gw": 28, "or": 227258, "#:": "▲", "op": 105, "gwr": 2012510, "gwp": 22,
         "pb": 0, "tm": 1, "tc": "4", "£": 100.2},
        {"gw": 29, "or": 167366, "#:": "▼", "op": 49, "gwr": 3453322, "gwp": 50,
         "pb": 3, "tm": 0, "tc": "4", "£": 100.1},
        {"gw": 30, "or": 2924653, "#:": "▲", "op": 83, "gwr": 3009234, "gwp": 76,
         "pb": 5, "tm": 1, "tc": "16", "£": 100},
        {"gw": 31, "or": 3398543, "#:": "▲", "op": 47, "gwr": 4561213, "gwp": 42,
         "pb": 0, "tm": 1, "tc": "0", "£": 100.2},
        {"gw": 32, "or": 3228234, "#:": 234, "op": 98, "gwr": 1031000, "gwp": 60,
         "pb": 3, "tm": 0, "tc": "4", "£": 100.1},
        {"gw": 33, "or": 79512, "#:": "▲", "op": 44, "gwr": 3061510, "gwp": 76,
         "pb": 5, "tm": 1, "tc": "4", "£": 100},
        {"gw": 34, "or": 237258, "#:": "▲", "op": 105, "gwr": 321510, "gwp": 52,
         "pb": 0, "tm": 1, "tc": "4", "£": 100.2},
        {"gw": 35, "or": 167366, "#:": "▼", "op": 49, "gwr": 35322, "gwp": 50,
         "pb": 3, "tm": 0, "tc": "4", "£": 100.1},
        {"gw": 36, "or": 924653, "#:": "▲", "op": 83, "gwr": 310934, "gwp": 76,
         "pb": 5, "tm": 1, "tc": "16", "£": 100},
        {"gw": 37, "or": 398543, "#:": "▲", "op": 47, "gwr": 456621, "gwp": 42,
         "pb": 0, "tm": 1, "tc": "0", "£": 100.2},
        {"gw": 38, "or": 238234, "#:": "▼", "op": 98, "gwr": 230000, "gwp": 60,
         "pb": 3, "tm": 0, "tc": "4", "£": 100.1}
    ]
    data = sort_table_data(data, sort_by, order,
                           allowed_fields=['gw', 'or', 'op', 'gwp', 'gwr', "#:", "pb", "tm", "tc", "£"])
    return jsonify(data)

# --- OFFENCE PAGE ---


@app.route("/<int:team_id>/team/offence")
def offence(team_id):
    flash_if_preseason()
    return render_template("offence.html",
                           team_id=team_id,
                           current_gw=session.get('current_gw'),
                           manager=g.manager,
                           sort_by=request.args.get(
                               'sort_by', 'goals_scored'),
                           order=request.args.get('order', 'desc'),
                           current_page='offence')

# --- DEFENCE PAGE ---


@app.route("/<int:team_id>/team/defence")
def defence(team_id):
    flash_if_preseason()
    return render_template("defence.html",
                           team_id=team_id,
                           current_gw=session.get('current_gw'),
                           manager=g.manager,
                           sort_by=request.args.get('sort_by', 'starts'),
                           order=request.args.get('order', 'desc'),
                           current_page='defence')

# --- POINTS PAGE ---


@app.route("/<int:team_id>/team/points")
def points(team_id):
    flash_if_preseason()
    return render_template("points.html",
                           team_id=team_id,
                           current_gw=session.get('current_gw'),
                           manager=g.manager,
                           sort_by=request.args.get(
                               'sort_by', 'total_points'),
                           order=request.args.get('order', 'desc'),
                           current_page='points')

# --- PER 90 PAGE ---


@app.route("/<int:team_id>/team/per_90")
def per_90(team_id):
    flash("Season hasn't started yet. No data available.", "info")
    return render_template("per_90.html",
                           team_id=team_id,
                           current_gw=session.get('current_gw'),
                           manager=g.manager,
                           sort_by=request.args.get('sort_by', 'goals_per90'),
                           order=request.args.get('order', 'desc'),
                           current_page='per_90')

# --- TEAMS PAGE ---


@app.route("/<int:team_id>/team/teams")
def teams(team_id):
    flash("Season hasn't started yet. No data available.", "info")
    try:
        # grab current GW from session
        current_gw = session.get('current_gw', '__')

        # default sort key + order
        default_sort_by = 'starts'
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


# --- MINI LEAGUES PAGE ---


@app.route("/<int:league_id>/leagues/mini_leagues")
def mini_leagues(league_id):

    # 1️⃣ ensure we know the current GW
    current_gw = session.get("current_gw") or get_current_gw()
    session["current_gw"] = current_gw

    if current_gw is None:
        flash("Mini-leagues are unavailable before the season starts.", "warning")
        team_id = session.get("team_id")
        if team_id:
            return redirect(url_for("manager", team_id=team_id))
        return redirect(url_for("index"))

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
    # 1️⃣ Parse query params
    table = request.args.get("table",      default="goals")
    team_id = request.args.get("team_id",    type=int)
    league_id = request.args.get("league_id",  type=int)
    sort_by = request.args.get("sort_by",    default=None)
    order = request.args.get("order",      default="desc")
    current_gw = session.get("current_gw")
    max_show = request.args.get("max_show",   2, type=int)

    # 2️⃣ Validate required params
    if table == "mini_league":
        if league_id is None or current_gw is None:
            return jsonify({"error": "Missing league_id or current_gw"}), 400
    else:
        # if team_id is None or current_gw is None:
        if team_id is None:
            return jsonify({"error": "Missing team_id or current_gw"}), 400

    # 3️⃣ Load or build static blob for this GW
    conn = sqlite3.connect(DATABASE, check_same_thread=False)
    cur = conn.cursor()
    cur.execute(
        "SELECT data FROM static_player_info WHERE gameweek = ?", (current_gw,)
    )
    row = cur.fetchone()
    if row:
        static_blob = {int(pid): blob for pid,
                       blob in json.loads(row[0]).items()}
    else:
        static_blob = build_player_info(get_static_data())
        cur.execute(
            "INSERT OR REPLACE INTO static_player_info (gameweek,data) VALUES (?,?)",
            (current_gw, json.dumps(static_blob))
        )
        conn.commit()

    # 4️⃣ Handle mini-league table  ────────────────────────────
    if table == "mini_league":
        static_data = get_static_data()

        # a) Try cache
        cur.execute(
            "SELECT data FROM mini_league_cache WHERE league_id=? AND gameweek=? AND team_id=? AND max_show=?",
            (league_id, current_gw, team_id, max_show)
        )
        row = cur.fetchone()
        if row:
            players = json.loads(row[0])
            rev = (order.lower() == "desc")
            players.sort(key=lambda o: o.get(sort_by, 0), reverse=rev)
            conn.close()
            return jsonify(players=players, manager=g.manager)

        # b) Cache miss → fetch managers
        managers = get_team_ids_from_league(league_id, max_show)
        append_current_manager(managers, team_id, league_id, logger=app.logger)

        # c) Build summaries and merge metadata
        players = []
        for m in managers:
            summary = get_team_mini_league_summary(m["entry"], static_data)

            # instead of popping, just read the entry and leave `m` intact:
            entry_id = m["entry"]
            meta = {**m, "team_id": entry_id}

            summary.update(meta)
            players.append(summary)

            values = [p.get(sort_by) for p in players]
            print(f"Sorting by `{sort_by}`, got values: {values}")

            # find all the indices where it’s None
            bad_idxs = [i for i, v in enumerate(values) if v is None]
            if bad_idxs:
                print("→ None at positions:", bad_idxs)
                for i in bad_idxs:
                    print(f"  player[{i}] = {players[i]}")

            # d) Final sort & annotate
            rev = (order.lower() == "desc")
            players.sort(key=lambda o: o.get(sort_by, 0), reverse=rev)

            # overall‐season leader (same as your existing call)
            leader_pts = get_overall_league_leader_total()

            # mini‐league leader = max total_points among this mini‐league’s players
            league_leader_pts = max((p.get("total_points", 0)
                                    for p in players), default=0)

            print(f"league_leader_pts: {league_leader_pts}")

            for p in players:
                # points behind the mini‐league’s top scorer
                p["pts_behind_league_leader"] = p.get(
                    "total_points", 0) - league_leader_pts
                print(
                    f"pts_behind_league_leader: {p['pts_behind_league_leader']}")
                # points behind the overall league leader
                p["pts_behind_overall"] = p.get("total_points", 0) - leader_pts

                # your ordinal‐formatted season label
                p["years_active_label"] = ordinalformat(
                    p.get("years_active", 0))

        # e) Cache and return
        cur.execute(
            "INSERT OR REPLACE INTO mini_league_cache (league_id, gameweek, team_id, max_show, data) VALUES (?,?,?,?,?)",
            (league_id, current_gw, team_id, max_show, json.dumps(players))
        )
        conn.commit()
        conn.close()
        return jsonify(players=players, manager=g.manager)

    # ─── 5️⃣ Non-mini-league branches ─────────────────────────
    cur.execute(
        "SELECT data FROM team_player_info WHERE team_id=? AND gameweek=?",
        (team_id, current_gw)
    )
    row = cur.fetchone()
    if row:
        team_blob = {int(pid): blob for pid,
                     blob in json.loads(row[0]).items()}
    else:
        team_blob = populate_player_info_all_with_live_data(
            team_id, static_blob, get_static_data())
        cur.execute(
            "INSERT OR REPLACE INTO team_player_info (team_id,gameweek,data) VALUES (?,?,?)",
            (team_id, current_gw, json.dumps(team_blob))
        )
        conn.commit()

    # ✅ Add filtering logic here
    if table != "teams":
        selected_positions = request.args.get("selected_positions", "")
        if selected_positions:
            positions = set(selected_positions.split(","))
            team_blob = {
                pid: p
                for pid, p in team_blob.items()
                if str(p["element_type"]) in positions
            }
        else:
            # no positions selected → return no players
            team_blob = {}

    conn.close()

    if table == "teams":
        # 1️⃣ Aggregate all players into one object per club
        stats = aggregate_team_stats(team_blob)

        # 2️⃣ Turn into a list and sort by the chosen metric
        sorted_stats = sorted(
            [team for team in stats.values() if team.get(sort_by, 0) != 0],
            key=lambda team: team.get(sort_by, 0),
            reverse=(order == "desc")
        )
        print(f"🚀 TEAMS branch – {len(sorted_stats)} clubs aggregated")

        # 3️⃣ Extract top five unique clubs for badges
        top5 = []
        seen = set()
        for club in sorted_stats:
            code = club["team_code"]
            if code not in seen:
                seen.add(code)
                top5.append({
                    "team_code": club["team_code"],
                    "team_name": club["team_name"]
                })
                if len(top5) == 5:
                    break
        print("🎖️ Top-5 badges:", top5)

        # 4️⃣ Respond with exactly one object per club
        return jsonify(
            players=sorted_stats,      # <= list of (up to) 20 club stats
            players_images=top5,        # <= your badges
            manager=g.manager
        )
    else:  # This is for offence, defence and points table ///////////////////////////////////////////////
        players, images = filter_and_sort_players(team_blob, request.args)
        return jsonify(players=players, players_images=images, manager=g.manager)


if __name__ == "__main__":
    app.run(debug=True)

# In the terminal:
# export FLASK_ENV=development
# export FLASK_DEBUG=1
# flask run

# grep -r "print(" modules/
# That will find all the print() calls inside your modules / directory (or wherever your app lives).
