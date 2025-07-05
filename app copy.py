from flask import session, request, render_template, flash, redirect, url_for
import os
import json
import sqlite3
import requests
from flask import (
    Flask, g, flash, jsonify,
    redirect, render_template, session,
    request, url_for
)
from modules.fetch_am_data import get_player_data_am
from modules.fetch_manager_data import get_manager_data, get_manager_history
from modules.fetch_all_tables import build_player_info, populate_player_info_all_with_live_data
from modules.fetch_teams_table import aggregate_team_stats
from modules.fetch_mini_leagues import get_team_ids_from_league, aggregate_player_info_per_team
from modules.aggregate_data import filter_and_sort_players
from modules.utils import (
    validate_team_id, get_max_users,
    get_static_data, get_current_gw,
    ordinalformat, thousands, territory_icon
)

app = Flask(__name__)
app.secret_key = os.urandom(24)
app.config["TEMPLATES_AUTO_RELOAD"] = True

# Jinja filters
app.jinja_env.filters["ordinalformat"] = ordinalformat
app.jinja_env.filters["thousands"] = thousands
app.jinja_env.filters["territory_icon"] = territory_icon

DATABASE = "page_views.db"

# Inject current manager into every template


@app.context_processor
def inject_current_manager():
    tid = session.get("team_id")
    if not tid:
        return {}
    mgr = get_manager_data(tid)
    return {"team_id": tid, "manager": mgr}

# Ensure current_gw in session


@app.before_request
def initialize_session():
    if 'current_gw' not in session:
        session['current_gw'] = get_current_gw()

# --- INDEX ---


@app.route("/", methods=["GET", "POST"])
def index():
    MAX_USERS = get_max_users()
    current_gw = session.get('current_gw', '__')
    if request.method == "GET":
        return render_template("index.html",
                               max_users=MAX_USERS,
                               current_gw=current_gw)
    # POST
    team_id = validate_team_id(request.form.get("team_id"), MAX_USERS)
    if team_id is None:
        flash("Invalid team ID", "error")
        return render_template("index.html",
                               max_users=MAX_USERS,
                               current_gw=current_gw)
    session['team_id'] = team_id
    return redirect(url_for("top_scorers", team_id=team_id))

# --- ABOUT ---


@app.route("/about")
def about():
    return render_template("about.html",
                           current_gw=session.get('current_gw'))

# --- CHIPS ---


@app.route("/<int:team_id>/team/chips")
def chips(team_id):
    try:
        return render_template("chips.html",
                               team_id=team_id,
                               current_gw=session.get('current_gw'),
                               manager=get_manager_data(team_id),
                               history=get_manager_history(team_id),
                               current_page='chips')
    except Exception as e:
        flash(f"Error: {e}", "error")
        return redirect(url_for("index"))

# --- TOP SCORERS PAGE ---


@app.route("/<int:team_id>/team/top_scorers")
def top_scorers(team_id):
    return render_template("top_scorers.html",
                           team_id=team_id,
                           current_gw=session.get('current_gw'),
                           sort_by=request.args.get(
                               'sort_by', 'goals_scored_team'),
                           order=request.args.get('order', 'desc'),
                           current_page='top_scorers')

# --- STARTS PAGE ---


@app.route("/<int:team_id>/team/starts")
def starts(team_id):
    return render_template("starts.html",
                           team_id=team_id,
                           current_gw=session.get('current_gw'),
                           sort_by=request.args.get('sort_by', 'starts_team'),
                           order=request.args.get('order', 'desc'),
                           current_page='starts')

# --- POINTS PAGE ---


@app.route("/<int:team_id>/team/points")
def points(team_id):
    return render_template("points.html",
                           team_id=team_id,
                           current_gw=session.get('current_gw'),
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
        default_sort_by = 'starts_team'
        default_order = 'asc'

        # allow user to override via query-string
        sort_by = request.args.get('sort_by', default_sort_by)
        order = request.args.get('order',   default_order)

        # render your teams.html — manager is injected by your context‐processor,
        # and tableType='teams' will drive the AJAX into the aggregate_team_stats branch
        return render_template(
            "teams.html",
            team_id=team_id,
            current_gw=current_gw,
            sort_by=sort_by,
            order=order,
            current_page='teams'
        )

    except ValueError:
        flash("Team ID must be a valid number", "error")
    except Exception as e:
        flash(f"Error loading Teams page: {e}", "error")

    return redirect(url_for("index"))


# --- ASSISTANT MANAGERS PAGE ---


@app.route("/<int:team_id>/team/am")
def am(team_id):
    return render_template("assistant_managers.html",
                           team_id=team_id,
                           current_gw=session.get('current_gw'),
                           sort_by=request.args.get('sort_by', 'total_points'),
                           order=request.args.get('order', 'desc'),
                           current_page='am')

# --- MINI LEAGUES PAGE ---


@app.route("/<int:league_id>/leagues/mini_leagues")
def mini_leagues(league_id):
    # 1️⃣ get the mini-league standings
    managers = get_team_ids_from_league(league_id, max_managers=10)

    # 2️⃣ pull in your cached static_blob
    current_gw = session.get("current_gw")
    conn = sqlite3.connect(DATABASE, check_same_thread=False)
    cur = conn.cursor()

    # ensure your cache tables exist...
    # (same DDL as in get_sorted_players)

    # static_blob
    cur.execute(
        "SELECT data FROM static_player_info WHERE gameweek = ?", (current_gw,))
    row = cur.fetchone()
    if row:
        static_blob = {int(k): v for k, v in json.loads(row[0]).items()}
    else:
        static_blob = build_player_info(get_static_data())
        cur.execute(
            "INSERT OR REPLACE INTO static_player_info (gameweek,data) VALUES (?,?)",
            (current_gw, json.dumps(static_blob)),
        )
        conn.commit()

    # 3️⃣ for each manager, load or build their team_blob
    all_team_player_info = []
    for mgr in managers:
        entry_id = mgr["entry"]
        # try cache
        cur.execute(
            "SELECT data FROM team_player_info WHERE team_id = ? AND gameweek = ?",
            (entry_id, current_gw),
        )
        row = cur.fetchone()
        if row:
            team_blob = {int(k): v for k, v in json.loads(row[0]).items()}
        else:
            team_blob = populate_player_info_all_with_live_data(
                entry_id, static_blob, get_static_data()
            )
            cur.execute(
                "INSERT OR REPLACE INTO team_player_info (team_id,gameweek,data) VALUES (?,?,?)",
                (entry_id, current_gw, json.dumps(team_blob)),
            )
            conn.commit()

        # convert blob dict→list of player-dicts
        player_list = list(team_blob.values())
        all_team_player_info.append((entry_id, player_list, mgr))

    conn.close()

    # 4️⃣ aggregate across each manager's squad
    aggregated = aggregate_player_info_per_team(all_team_player_info)

    # 5️⃣ apply sorting and slicing as before
    sort_by = request.args.get("sort_by", "goals_scored_team")
    order = request.args.get("order", "desc")
    aggregated.sort(
        key=lambda o: o.get(sort_by, 0),
        reverse=(order == "desc"),
    )

    # top 5 badges
    top5 = [{"team_id": o["team_id"], "team_name": o["team_name"]}
            for o in aggregated[:5]]

    # 6️⃣ finally render
    return render_template(
        "mini_leagues.html",
        league_id=league_id,
        current_gw=current_gw,
        sort_by=sort_by,
        order=order,
        players=aggregated,
        players_images=top5,
        current_page="mini_leagues",
    )


# --- GET SORTED PLAYERS (unified AJAX) ---


@app.route("/get-sorted-players")
def get_sorted_players():
    team_id = request.args.get("team_id",    type=int)
    table = request.args.get("table",      default="goals")
    sort_by = request.args.get("sort_by",    default=None)
    order = request.args.get("order",      default="desc")
    current_gw = session.get("current_gw")

    print(
        f"\n🔍 [REQUEST] team_id={team_id!r} table={table!r} sort_by={sort_by!r} order={order!r} current_gw={current_gw!r}")

    if not team_id or not current_gw:
        print("⚠️ Missing team_id or current_gw — bailing.")
        return jsonify({"error": "Missing team_id or current_gw"}), 400

    conn = sqlite3.connect(DATABASE, check_same_thread=False)
    cur = conn.cursor()

    # ensure cache tables exist
    cur.execute("""
      CREATE TABLE IF NOT EXISTS static_player_info (
        gameweek INTEGER PRIMARY KEY,
        data     TEXT    NOT NULL
      )
    """)
    cur.execute("""
      CREATE TABLE IF NOT EXISTS team_player_info (
        team_id  INTEGER,
        gameweek INTEGER,
        data     TEXT    NOT NULL,
        PRIMARY KEY(team_id,gameweek)
      )
    """)

    # ——— static skeleton ———
    cur.execute(
        "SELECT data FROM static_player_info WHERE gameweek = ?",
        (current_gw,)
    )
    row = cur.fetchone()
    print("📦 static cache hit? ", bool(row))
    if row:
        raw = json.loads(row[0])
        # JSON keys come back as strings; convert to ints
        static_blob = {int(pid): blob for pid, blob in raw.items()}
    else:
        static_blob = build_player_info(get_static_data())
        print("⚙️ built new static_blob with", len(static_blob), "entries")
        cur.execute(
            "INSERT OR REPLACE INTO static_player_info (gameweek,data) VALUES(?,?)",
            (current_gw, json.dumps(static_blob))
        )
        conn.commit()

    # ——— team overlay ———
    cur.execute(
        "SELECT data FROM team_player_info WHERE team_id = ? AND gameweek = ?",
        (team_id, current_gw)
    )
    row = cur.fetchone()
    print("📦 team cache hit?   ", bool(row))
    if row:
        raw = json.loads(row[0])
        team_blob = {int(pid): blob for pid, blob in raw.items()}
    else:
        team_blob = populate_player_info_all_with_live_data(
            team_id, static_blob, get_static_data()
        )
        print("⚙️ built new team_blob with", len(team_blob), "entries")
        cur.execute(
            "INSERT OR REPLACE INTO team_player_info (team_id,gameweek,data) VALUES(?,?,?)",
            (team_id, current_gw, json.dumps(team_blob))
        )
        conn.commit()

    # debug: sample entries
    sample = list(team_blob.items())[:5]
    for pid, p in sample:
        print(
            f"   🔎 pid={pid} | cost={p.get('cost')} | starts_team={p.get('starts_team')} | goals_scored_team={p.get('goals_scored_team')}")

    conn.close()

    # dispatch by table type
    # … earlier in get_sorted_players …

    if table == "teams":
        # 1️⃣ Aggregate all players into one object per club
        stats = aggregate_team_stats(team_blob)
        # stats: { team_code: { ..., "team_code":code, "team_name": name, … }, … }

        # 2️⃣ Turn into a list and sort by the chosen metric
        sorted_stats = sorted(
            stats.values(),
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
            players_images=top5        # <= your badges
        )

    if table == "am":
        print("🚀 AM branch")
        am_blob = get_player_data_am(get_static_data())
        players, images = filter_and_sort_players(am_blob, request.args)
        print(f"📝 AM returned {len(players)} players")
        return jsonify(players=players, players_images=images)

    # default: goals / starts / points / top_scorers etc.
    print("🚀 DEFAULT branch, filtering team_blob")
    players, images = filter_and_sort_players(team_blob, request.args)
    print(f"📝 DEFAULT returned {len(players)} players, {len(images)} images\n")
    return jsonify(players=players, players_images=images)
