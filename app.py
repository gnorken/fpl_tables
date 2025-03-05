from flask import g, Flask, flash, jsonify, redirect, render_template, session, request
import json
import sqlite3

from modules.fetch_manager_data import get_manager_data, get_manager_history
from modules.fetch_goals_table import get_player_data_goals, get_live_data_goals
from modules.fetch_starts_table import get_player_data_starts, get_live_data_starts
from modules.fetch_points_table import get_player_data_points, get_live_data_points
from modules.aggregate_data import filter_and_sort_players
from modules.utils import validate_team_id, get_max_users, get_static_data, get_current_gw

import os
import requests

app = Flask(__name__)

app.secret_key = os.urandom(24)  # Generates a random 24-byte key

DATABASE = "page_views.db"

# Utility function to get a database connection


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(DATABASE, check_same_thread=False)
        g.db.row_factory = sqlite3.Row  # Enable dict-like access to rows
        # Enable WAL mode for better concurrency
        g.db.execute("PRAGMA journal_mode=WAL;")
    return g.db


# Middleware for making sure current gameweek is in session regardless of URL entry point


@app.before_request
def initialize_session():
    if 'current_gw' not in session:
        session['current_gw'] = get_current_gw()


# GET route index.html
# POST route redirects to /top_scorers
@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "GET":
        MAX_USERS = get_max_users()
        CURRENT_GW = session['current_gw']
        return render_template("index.html", max_users=MAX_USERS, current_gw=CURRENT_GW, manager=None)
    else:   # For POST
        MAX_USERS = get_max_users()
        team_id = request.form.get("team_id")
        team_id = validate_team_id(team_id, MAX_USERS)
        if team_id is None:
            return render_template("index.html", max_users=MAX_USERS, manager=None)
        return redirect(f"/{team_id}/team/top_scorers")


# About route
@app.route("/about")
def about():
    CURRENT_GW = session['current_gw']
    return render_template("about.html", current_gw=CURRENT_GW)

# team_page


@app.route("/<int:team_id>/team/chips")
def chips(team_id):
    CURRENT_GW = session['current_gw']
    try:
        # Get manager and player data
        manager = get_manager_data(team_id)
        history = get_manager_history(team_id)
        print(f"history: {history}")
        print("Manager data:", manager)
        return render_template("chips.html",
                               team_id=team_id,
                               current_gw=CURRENT_GW,
                               manager=manager,
                               history=history,
                               current_page='chips'
                               )

    except ValueError:
        flash("Team ID must be a valid number", "error")
    except requests.exceptions.RequestException as e:
        flash(f"Error fetching data: {e}", "error")

    return redirect("/")

# TOP_SCORERS
# Dynamic team route for top_scorers


@app.route("/<int:team_id>/team/top_scorers")
def top_scorers(team_id):
    try:
        # Default to 'N/A' if not set
        current_gw = session.get('current_gw', '__')

        # Set default values for sort_by and order
        default_sort_by = 'goals_scored_team'
        default_order = 'asc'  # Reverse so the toggle works

        # Get query parameters, using default values if not provided
        sort_by = request.args.get('sort_by', default_sort_by)
        order = request.args.get('order', default_order)

        # Get manager and player data
        manager = get_manager_data(team_id)

        return render_template("top_scorers.html",
                               team_id=team_id,
                               current_gw=current_gw,
                               manager=manager,
                               sort_by=sort_by,
                               order=order,
                               current_page='top_scorers'
                               )

    except ValueError:
        flash("Team ID must be a valid number", "error")
    except requests.exceptions.RequestException as e:
        flash(f"Error fetching data: {e}", "error")

    return redirect("/")


# AJAX for goals table
@app.route("/get-sorted-players-goals")
def get_sorted_players_goals():
    try:
        print("Query Parameters:", request.args)
        # Get team_id and sort_by from the query parameters
        team_id = request.args.get('team_id', type=int)

        if not team_id:
            return jsonify({'error': 'Missing team_id parameter'}), 400

        # Get data for goal_scorers table from JSON or API
        # Connect to the database
        conn = sqlite3.connect("page_views.db", check_same_thread=False)
        cursor = conn.cursor()

        # Check if the gameweek has changed
        # Get the current gameweek from the session
        current_gameweek = session.get('current_gw')
        cursor.execute("SELECT DISTINCT gameweek FROM player_info_goals")
        stored_gameweek = cursor.fetchone()

        if not stored_gameweek or stored_gameweek[0] != current_gameweek:
            # Clear the database entirely if the gameweek has changed
            cursor.execute("DELETE FROM player_info_goals")
            # Insert new gameweek value in the 'player_info' table
            cursor.execute("""
                INSERT INTO player_info_goals (team_id, data, gameweek)
                VALUES (?, ?, ?)
            """, (-1, "{}", current_gameweek))  # Placeholder entry to track the gameweek
            conn.commit()

        # Try to fetch existing player_info from the database
        cursor.execute(
            "SELECT data FROM player_info_goals WHERE team_id = ?", (team_id,))
        row = cursor.fetchone()

        if row:
            # Deserialize JSON string back into a dictionary
            player_info = json.loads(row[0])
        else:
            # If no data exists, generate player_info
            static_data = get_static_data()
            # Get player data for 'goals table'
            player_info = get_player_data_goals(static_data)
            # Get team-specific player data for 'goals table'
            player_info = get_live_data_goals(
                team_id, player_info, static_data)

            # Save the new player_info to the database
            player_info_json = json.dumps(player_info)
            cursor.execute("""
                INSERT INTO player_info_goals (team_id, data, gameweek)
                VALUES (?, ?, ?)
            """, (team_id, player_info_json, current_gameweek))
            conn.commit()

        conn.close()

        # Filter and sort players
        top_scorers, top_scorers_images = filter_and_sort_players(
            player_info, request.args)

        if not top_scorers:
            return jsonify({'error': 'No players to display', 'players': []}), 200

        # Prepare data to send back to the client
        response_data = {
            'players': top_scorers,
            'players_images': top_scorers_images
        }
        # print("Response Data:", response_data)

        return jsonify(response_data)

    except Exception as e:
        return jsonify({'error': str(e)}), 500


# STARTS
# Dynamic team route for starts
@app.route("/<int:team_id>/team/starts")
def starts(team_id):
    try:
        # Default to 'N/A' if not set
        current_gw = session.get('current_gw', '__')

        # Set default values for sort_by and order
        default_sort_by = 'starts_team'
        default_order = 'asc'  # Reverse so the toggle works

        # Get query parameters, using default values if not provided
        sort_by = request.args.get('sort_by', default_sort_by)
        order = request.args.get('order', default_order)

        # Get manager and player data
        manager = get_manager_data(team_id)

        return render_template("starts.html",
                               team_id=team_id,
                               current_gw=current_gw,
                               manager=manager,
                               sort_by=sort_by,
                               order=order,
                               current_page='starts'
                               )

    except ValueError:
        flash("Team ID must be a valid number", "error")
    except requests.exceptions.RequestException as e:
        flash(f"Error fetching data: {e}", "error")

    return redirect("/")

# AJAX for starts table


@app.route("/get-sorted-players-starts")
def get_sorted_players_starts():
    try:
        print("Query Parameters:", request.args)
        # Get team_id and sort_by from the query parameters
        team_id = request.args.get('team_id', type=int)

        if not team_id:
            return jsonify({'error': 'Missing team_id parameter'}), 400

        # Get data for goal_scorers table from JSON or API
        # Connect to the database
        conn = sqlite3.connect("page_views.db", check_same_thread=False)
        cursor = conn.cursor()

        # Check if the gameweek has changed
        # Get the current gameweek from the session
        current_gameweek = session.get('current_gw')
        cursor.execute("SELECT DISTINCT gameweek FROM player_info_starts")
        stored_gameweek = cursor.fetchone()

        if not stored_gameweek or stored_gameweek[0] != current_gameweek:
            # Clear the database entirely if the gameweek has changed
            cursor.execute("DELETE FROM player_info_starts")
            # Insert new gameweek value in the 'player_info' table
            cursor.execute("""
                INSERT INTO player_info_starts (team_id, data, gameweek)
                VALUES (?, ?, ?)
            """, (-1, "{}", current_gameweek))  # Placeholder entry to track the gameweek
            conn.commit()

        # Try to fetch existing player_info from the database
        cursor.execute(
            "SELECT data FROM player_info_starts WHERE team_id = ?", (team_id,))
        row = cursor.fetchone()

        if row:
            # Deserialize JSON string back into a dictionary
            player_info = json.loads(row[0])
        else:
            # If no data exists, generate player_info
            static_data = get_static_data()
            # Get player data for 'starts table'
            player_info = get_player_data_starts(static_data)
            # Get team-specific player data for 'starts table'
            player_info = get_live_data_starts(
                team_id, player_info, static_data)

            # Save the new player_info to the database
            player_info_json = json.dumps(player_info)
            cursor.execute("""
                INSERT INTO player_info_starts (team_id, data, gameweek)
                VALUES (?, ?, ?)
            """, (team_id, player_info_json, current_gameweek))
            conn.commit()

        conn.close()

        # Filter and sort players
        top_scorers, top_scorers_images = filter_and_sort_players(
            player_info, request.args)

        if not top_scorers:
            return jsonify({'error': 'No players to display', 'players': []}), 200

        # Prepare data to send back to the client
        response_data = {
            'players': top_scorers,
            'players_images': top_scorers_images
        }

        return jsonify(response_data)

    except Exception as e:
        return jsonify({'error': str(e)}), 500


# POINTS
# Dynamic team route for points
@app.route("/<int:team_id>/team/points")
def points(team_id):
    try:
        # Default to 'N/A' if not set
        current_gw = session.get('current_gw', '__')

        # Set default values for sort_by and order
        default_sort_by = 'total_points_team'
        default_order = 'asc'  # Reverse so the toggle works

        # Get query parameters, using default values if not provided
        sort_by = request.args.get('sort_by', default_sort_by)
        order = request.args.get('order', default_order)

        # Get manager and player data
        manager = get_manager_data(team_id)

        return render_template("points.html",
                               team_id=team_id,
                               current_gw=current_gw,
                               manager=manager,
                               sort_by=sort_by,
                               order=order,
                               current_page='points'
                               )

    except ValueError:
        flash("Team ID must be a valid number", "error")
    except requests.exceptions.RequestException as e:
        flash(f"Error fetching data: {e}", "error")

    return redirect("/")


# AJAX for points table
@app.route("/get-sorted-players-points")
def get_sorted_players_points():
    try:
        print("Query Parameters:", request.args)
        # Get team_id and sort_by from the query parameters
        team_id = request.args.get('team_id', type=int)

        if not team_id:
            return jsonify({'error': 'Missing team_id parameter'}), 400

        # Get data for goal_scorers table from JSON or API
        # Connect to the database
        conn = sqlite3.connect("page_views.db", check_same_thread=False)
        cursor = conn.cursor()

        # Check if the gameweek has changed
        # Get the current gameweek from the session
        current_gameweek = session.get('current_gw')
        cursor.execute("SELECT DISTINCT gameweek FROM player_info_points")
        stored_gameweek = cursor.fetchone()

        if not stored_gameweek or stored_gameweek[0] != current_gameweek:
            # Clear the database entirely if the gameweek has changed
            cursor.execute("DELETE FROM player_info_points")
            # Insert new gameweek value in the 'player_info' table
            cursor.execute("""
                INSERT INTO player_info_points (team_id, data, gameweek)
                VALUES (?, ?, ?)
            """, (-1, "{}", current_gameweek))  # Placeholder entry to track the gameweek
            conn.commit()

        # Try to fetch existing player_info from the database
        cursor.execute(
            "SELECT data FROM player_info_points WHERE team_id = ?", (team_id,))
        row = cursor.fetchone()

        if row:
            # Deserialize JSON string back into a dictionary
            player_info = json.loads(row[0])
        else:
            # If no data exists, generate player_info
            static_data = get_static_data()
            # Get player data for 'starts table'
            player_info = get_player_data_points(static_data)
            # Get team-specific player data for 'starts table'
            player_info = get_live_data_points(
                team_id, player_info, static_data)

            # Save the new player_info to the database
            player_info_json = json.dumps(player_info)
            cursor.execute("""
                INSERT INTO player_info_points (team_id, data, gameweek)
                VALUES (?, ?, ?)
            """, (team_id, player_info_json, current_gameweek))
            conn.commit()

        conn.close()

        # Filter and sort players
        top_scorers, top_scorers_images = filter_and_sort_players(
            player_info, request.args)

        if not top_scorers:
            return jsonify({'error': 'No players to display', 'players': []}), 200

        # Prepare data to send back to the client
        response_data = {
            'players': top_scorers,
            'players_images': top_scorers_images
        }

        return jsonify(response_data)

    except Exception as e:
        return jsonify({'error': str(e)}), 500


app.config["TEMPLATES_AUTO_RELOAD"] = True

if __name__ == "__main__":
    app.run(debug=True)

# In the terminal:
# export FLASK_ENV=development
# export FLASK_DEBUG=1
# flask run
