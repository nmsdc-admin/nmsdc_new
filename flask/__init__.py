import json
import logging
import os
import sys
import uuid
from abc import ABC, abstractmethod
from functools import wraps
import importlib.metadata
from jinja2 import FileSystemLoader, Environment
import psycopg2

import flask
import requests
from flasgger import Swagger
from flask import Flask, Response, jsonify, request, send_from_directory,render_template
from flask_sock import Sock

from ..base import VannaBase
from .assets import css_content, html_content, js_content
from .auth import AuthInterface, NoAuth , BasicAuth
from flask_cors import CORS


class Cache(ABC):
    """
    Define the interface for a cache that can be used to store data in a Flask app.
    """

    @abstractmethod
    def generate_id(self, *args, **kwargs):
        """
        Generate a unique ID for the cache.
        """
        pass

    @abstractmethod
    def get(self, id, field):
        """
        Get a value from the cache.
        """
        pass

    @abstractmethod
    def get_all(self, field_list) -> list:
        """
        Get all values from the cache.
        """
        pass

    @abstractmethod
    def set(self, id, field, value):
        """
        Set a value in the cache.
        """
        pass

    @abstractmethod
    def delete(self, id):
        """
        Delete a value from the cache.
        """
        pass


class MemoryCache(Cache):
    def __init__(self):
        self.cache = {}

    def generate_id(self, *args, **kwargs):
        return str(uuid.uuid4())

    def set(self, id, field, value):
        if id not in self.cache:
            self.cache[id] = {}

        self.cache[id][field] = value

    def get(self, id, field):
        if id not in self.cache:
            return None

        if field not in self.cache[id]:
            return None

        return self.cache[id][field]

    def get_all(self, field_list) -> list:
        return [
            {"id": id, **{field: self.get(id=id, field=field) for field in field_list}}
            for id in self.cache
        ]

    def delete(self, id):
        if id in self.cache:
            del self.cache[id]


class VannaFlaskAPI:
    flask_app = None

    def requires_cache(self, required_fields, optional_fields=[]):
        def decorator(f):
            @wraps(f)
            def decorated(*args, **kwargs):
                id = request.args.get("id")

                if id is None:
                    id = request.json.get("id")
                    if id is None:
                        return jsonify({"type": "error", "error": "No id provided"})

                for field in required_fields:
                    if self.cache.get(id=id, field=field) is None:
                        return jsonify({"type": "error", "error": f"No {field} found"})

                field_values = {
                    field: self.cache.get(id=id, field=field) for field in required_fields
                }

                for field in optional_fields:
                    field_values[field] = self.cache.get(id=id, field=field)

                # Add the id to the field_values
                field_values["id"] = id

                return f(*args, **field_values, **kwargs)

            return decorated

        return decorator

    def requires_auth(self, f):
        @wraps(f)
        def decorated(*args, **kwargs):
            user = self.auth.get_user(flask.request)

            if not self.auth.is_logged_in(user):
                return jsonify({"type": "not_logged_in", "html": self.auth.login_form()})

            # Pass the user to the function
            return f(*args, user=user, **kwargs)

        return decorated

    def __init__(
        self,
        vn: VannaBase,
        cache: Cache = MemoryCache(),
        auth: AuthInterface = NoAuth(),
        debug=True,
        allow_llm_to_see_data=True,
        chart=True,
    ):
        """
        Expose a Flask API that can be used to interact with a Vanna instance.

        Args:
            vn: The Vanna instance to interact with.
            cache: The cache to use. Defaults to MemoryCache, which uses an in-memory cache. You can also pass in a custom cache that implements the Cache interface.
            auth: The authentication method to use. Defaults to NoAuth, which doesn't require authentication. You can also pass in a custom authentication method that implements the AuthInterface interface.
            debug: Show the debug console. Defaults to True.
            allow_llm_to_see_data: Whether to allow the LLM to see data. Defaults to False.
            chart: Whether to show the chart output in the UI. Defaults to True.

        Returns:
            None
        """

        self.flask_app = Flask(__name__)
        CORS(self.flask_app)
        self.flask_app.secret_key = "df2b3a4c5e6f7g8h9i0j1k2l3m4n5o6p"

        



        self.swagger = Swagger(
          self.flask_app, template={"info": {"title": "Vanna API"}}
        )
        self.sock = Sock(self.flask_app)
        self.ws_clients = []
        self.vn = vn
        self.auth = auth
        self.cache = cache
        self.debug = debug
        self.allow_llm_to_see_data = allow_llm_to_see_data
        self.chart = chart
        self.config = {
          "debug": debug,
          "allow_llm_to_see_data": allow_llm_to_see_data,
          "chart": chart,
        }
        log = logging.getLogger("werkzeug")
        log.setLevel(logging.ERROR)

        if "google.colab" in sys.modules:
            self.debug = False
            print("Google Colab doesn't support running websocket servers. Disabling debug mode.")

        if self.debug:
            def log(message, title="Info"):
                [ws.send(json.dumps({'message': message, 'title': title})) for ws in self.ws_clients]

            self.vn.log = log
        
        @self.flask_app.route("/api/v0/get_config", methods=["GET"])
        @self.requires_auth
        def get_config(user: any):
            """
            Get the configuration for a user
            ---
            parameters:
              - name: user
                in: query
            responses:
              200:
                schema:
                  type: object
                  properties:
                    type:
                      type: string
                      default: config
                    config:
                      type: object
            """
            config = self.auth.override_config_for_user(user, self.config)
            return jsonify(
                {
                    "type": "config",
                    "config": config
                }
            )

        # Define a variable to hold the parent question ID
        self.parent_question_id = None

        @self.flask_app.route("/api/v0/generate_sql", methods=["GET"])
        @self.requires_auth
        def generate_sql(user: str):  # Expecting user to be a string (username or email)
            """
            Generate SQL from a question and save the history to the database (including SQL query)
            ---
            parameters:
              - name: question
                in: query
                type: string
                required: true
              - name: type
                in: query
                type: string
                required: false
                description: Indicates if the question is rewritten or original
            responses:
              200:
                schema:
                  type: object
                  properties:
                    type:
                      type: string
                      default: sql
                    id:
                      type: string
                    text:
                      type: string
            """
            print("Received request to generate SQL")  # Debug statement

            # Get the question and type from the request
            question = flask.request.args.get("question")
            question_type = flask.request.args.get("type", "original")
            print(f"Question received: {question}, Type: {question_type}")  # Debug statement

            # If no question is provided
            if question is None:
                print("No question provided")
                return jsonify({"type": "error", "error": "No question provided"}), 400

            print(f"User (from auth decorator): {user}")  # Debug statement

            # If the user is not authenticated
            if not user:
                print("User not authenticated")
                return jsonify({"type": "error", "error": "User not authenticated"}), 401

            # Generate a unique ID for the question
            id = self.cache.generate_id(question=question)
            sql = vn.generate_sql(question=question, allow_llm_to_see_data=self.allow_llm_to_see_data)

            # Debug: Log the generated SQL
            print(f"Generated SQL: {sql}")

            if sql is None or sql == "":
                print("Generated SQL is null or empty")
                return jsonify({"type": "error", "error": "SQL generation failed"}), 400

            # Cache the question and generated SQL
            self.cache.set(id=id, field="question", value=question)
            self.cache.set(id=id, field="sql", value=sql)

            # Check if the question is rewritten
            if question_type == "rewritten":
                # Use the parent question ID to save a follow-up question
                if self.parent_question_id is None:
                    print("Parent question ID is not set for the rewritten question")
                    return jsonify({"type": "error", "error": "No parent question ID available"}), 400

                try:
                    conn = psycopg2.connect(
                        host='localhost',
                        dbname='flat_table',
                        user='postgres',
                        password='admin',
                        port='5432'
                    )
                    print("Connected to PostgreSQL")
                except Exception as e:
                    print(f"Error connecting to database: {e}")
                    return jsonify({"type": "error", "error": "Database connection error"}), 500

                try:
                    with conn.cursor() as cursor:
                        cursor.execute(
                            """
                            INSERT INTO follow_up_questions (question_id, follow_up_question, username, sql, timestamp)
                            VALUES (%s, %s, %s, %s, NOW())
                            """,
                            (self.parent_question_id, question, user, sql)
                        )
                        conn.commit()
                        print(f"Rewritten question saved as follow-up for parent ID: {self.parent_question_id}")
                except Exception as e:
                    print(f"Error inserting follow-up question into database: {e}")
                    return jsonify({"type": "error", "error": "Database insertion error"}), 500
                finally:
                    conn.close()
                    print("Database connection closed")
            else:
                # If the question is not rewritten, save it as a new parent question
                self.parent_question_id = id  # Update the parent question ID

                try:
                    conn = psycopg2.connect(
                        host='localhost',
                        dbname='flat_table',
                        user='postgres',
                        password='admin',
                        port='5432'
                    )
                    print("Connected to PostgreSQL")
                except Exception as e:
                    print(f"Error connecting to database: {e}")
                    return jsonify({"type": "error", "error": "Database connection error"}), 500

                try:
                    with conn.cursor() as cursor:
                        cursor.execute(
                            """
                            INSERT INTO question_history (id, username, question, sql, timestamp)
                            VALUES (%s, %s, %s, %s, NOW())
                            """,
                            (id, user, question, sql)
                        )
                        conn.commit()
                        print(f"Parent question saved to database with ID: {id}")
                except Exception as e:
                    print(f"Error inserting into database: {e}")
                    return jsonify({"type": "error", "error": "Database insertion error"}), 500
                finally:
                    conn.close()
                    print("Database connection closed")

            # Return the generated SQL response
            if vn.is_sql_valid(sql=sql):
                return jsonify(
                    {
                        "type": "sql",
                        "id": id,
                        "text": sql,
                    }
                ), 200
            else:
                return jsonify(
                    {
                        "type": "text",
                        "id": id,
                        "text": sql,
                    }
                ), 200

        @self.flask_app.route("/api/v0/get_followup_questions", methods=["GET"])
        @self.requires_auth
        def get_followup_questions(user: str):
            """
            Fetch follow-up questions by question ID
            ---
            parameters:
              - name: question_id
                in: query
                type: string
                required: true
                description: The ID of the parent question to fetch follow-ups for
            responses:
              200:
                description: A list of follow-up questions
                schema:
                  type: object
                  properties:
                    type:
                      type: string
                      default: followup_questions
                    followups:
                      type: array
                      items:
                        type: object
                        properties:
                          follow_up_id:
                            type: string
                          question_id:
                            type: string
                          timestamp:
                            type: string
                          follow_up_question:
                            type: string
                          sql:
                            type: string
                          username:
                            type: string
              400:
                description: Bad request if `question_id` is missing
              500:
                description: Internal server error for database issues
            """
            # Get question_id from query parameters
            question_id = flask.request.args.get("question_id")
            if not question_id:
                return jsonify({"type": "error", "error": "Missing required parameter: question_id"}), 400

            try:
                conn = psycopg2.connect(
                    host='localhost',
                    dbname='flat_table',
                    user='postgres',
                    password='admin',
                    port='5432'
                )
                print("Connected to PostgreSQL")
            except Exception as e:
                print(f"Error connecting to database: {e}")
                return jsonify({"type": "error", "error": "Database connection error"}), 500

            followups = []
            try:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT follow_up_id, question_id, timestamp, follow_up_question, sql, username
                        FROM follow_up_questions
                        WHERE question_id = %s
                        """,
                        (question_id,)
                    )
                    results = cursor.fetchall()
                    for row in results:
                        followups.append({
                            "follow_up_id": row[0],
                            "question_id": row[1],
                            "timestamp": row[2].isoformat() if row[2] else None,
                            "follow_up_question": row[3],
                            "sql": row[4],
                            "username": row[5],
                        })
            except Exception as e:
                print(f"Error fetching follow-up questions: {e}")
                return jsonify({"type": "error", "error": "Error fetching follow-up questions"}), 500
            finally:
                conn.close()
                print("Database connection closed")

            return jsonify({
                "type": "followup_questions",
                "followups": followups
            }), 200



        @self.flask_app.route("/api/v0/generate_rewritten_question", methods=["GET"])
        @self.requires_auth
        def generate_rewritten_question(user: any):
            """
            Generate a rewritten question
            ---
            parameters:
              - name: last_question
                in: query
                type: string
                required: true
              - name: new_question
                in: query
                type: string
                required: true
            """

            last_question = flask.request.args.get("last_question")
            new_question = flask.request.args.get("new_question")

            rewritten_question = self.vn.generate_rewritten_question(last_question, new_question)

            return jsonify({"type": "rewritten_question", "question": rewritten_question})

        @self.flask_app.route("/api/v0/get_function", methods=["GET"])
        @self.requires_auth
        def get_function(user: any):
            """
            Get a function from a question
            ---
            parameters:
              - name: user
                in: query
              - name: question
                in: query
                type: string
                required: true
            responses:
              200:
                schema:
                  type: object
                  properties:
                    type:
                      type: string
                      default: function
                    id:
                      type: object
                    function:
                      type: string
            """
            question = flask.request.args.get("question")

            if question is None:
                return jsonify({"type": "error", "error": "No question provided"})

            if not hasattr(vn, "get_function"):
                return jsonify({"type": "error", "error": "This setup does not support function generation."})

            id = self.cache.generate_id(question=question)
            function = vn.get_function(question=question)

            if function is None:
                return jsonify({"type": "error", "error": "No function found"})

            if 'instantiated_sql' not in function:
                self.vn.log(f"No instantiated SQL found for {question} in {function}")
                return jsonify({"type": "error", "error": "No instantiated SQL found"})

            self.cache.set(id=id, field="question", value=question)
            self.cache.set(id=id, field="sql", value=function['instantiated_sql'])

            if 'instantiated_post_processing_code' in function and function['instantiated_post_processing_code'] is not None and len(function['instantiated_post_processing_code']) > 0:
                self.cache.set(id=id, field="plotly_code", value=function['instantiated_post_processing_code'])

            return jsonify(
                {
                    "type": "function",
                    "id": id,
                    "function": function,
                }
            )

        @self.flask_app.route("/api/v0/get_all_functions", methods=["GET"])
        @self.requires_auth
        def get_all_functions(user: any):
            """
            Get all the functions
            ---
            parameters:
              - name: user
                in: query
            responses:
              200:
                schema:
                  type: object
                  properties:
                    type:
                      type: string
                      default: functions
                    functions:
                      type: array
            """
            if not hasattr(vn, "get_all_functions"):
                return jsonify({"type": "error", "error": "This setup does not support function generation."})

            functions = vn.get_all_functions()

            return jsonify(
                {
                    "type": "functions",
                    "functions": functions,
                }
            )

        @self.flask_app.route("/api/v0/run_sql", methods=["GET"])
        @self.requires_auth
        @self.requires_cache(["sql"])
        def run_sql(user: any, id: str, sql: str):
            """
            Run SQL
            ---
            parameters:
              - name: user
                in: query
              - name: id
                in: query|body
                type: string
                required: true
            responses:
              200:
                schema:
                  type: object
                  properties:
                    type:
                      type: string
                      default: df
                    id:
                      type: string
                    df:
                      type: object
                    should_generate_chart:
                      type: boolean
            """
            try:
                if not vn.run_sql_is_set:
                    return jsonify(
                        {
                            "type": "error",
                            "error": "Please connect to a database using vn.connect_to_... in order to run SQL queries.",
                        }
                    )

                df = vn.run_sql(sql=sql)

                self.cache.set(id=id, field="df", value=df)

                return jsonify(
                    {
                        "type": "df",
                        "id": id,
                        "df": df.head(10).to_json(orient='records', date_format='iso'),
                        "should_generate_chart": self.chart and vn.should_generate_chart(df),
                    }
                )

            except Exception as e:
                return jsonify({"type": "sql_error", "error": str(e)})
        @self.flask_app.route("/api/v0/run_sql_direct", methods=["GET"])
        @self.requires_auth
        def run_sql_direct(user: any):
            """
            Run SQL Directly
            ---
            parameters:
              - name: user
                in: query
              - name: sql
                in: query
                type: string
                required: true
            responses:
              200:
                schema:
                  type: object
                  properties:
                    type:
                      type: string
                      default: df
                    df:
                      type: object
                    should_generate_chart:
                      type: boolean
            """
            try:
                # Retrieve the 'sql' parameter from the query string
                sql = flask.request.args.get("sql")
                if not sql:
                    return jsonify({"type": "error", "error": "Missing required parameter: sql"}), 400

                if not vn.run_sql_is_set:
                    return jsonify(
                        {
                            "type": "error",
                            "error": "Please connect to a database using vn.connect_to_... in order to run SQL queries.",
                        }
                    )

                # Execute the SQL query
                df = vn.run_sql(sql=sql)

                # Return the results as JSON
                return jsonify(
                    {
                        "type": "df",
                        "df": df.head(10).to_json(orient='records', date_format='iso'),
                        "should_generate_chart": self.chart and vn.should_generate_chart(df),
                    }
                )

            except Exception as e:
                return jsonify({"type": "sql_error", "error": str(e)})

        @self.flask_app.route("/api/v0/fix_sql", methods=["POST"])
        @self.requires_auth
        @self.requires_cache(["question", "sql"])
        def fix_sql(user: any, id: str, question: str, sql: str):
            """
            Fix SQL
            ---
            parameters:
              - name: user
                in: query
              - name: id
                in: query|body
                type: string
                required: true
              - name: error
                in: body
                type: string
                required: true
            responses:
              200:
                schema:
                  type: object
                  properties:
                    type:
                      type: string
                      default: sql
                    id:
                      type: string
                    text:
                      type: string
            """
            error = flask.request.json.get("error")

            if error is None:
                return jsonify({"type": "error", "error": "No error provided"})

            question = f"I have an error: {error}\n\nHere is the SQL I tried to run: {sql}\n\nThis is the question I was trying to answer: {question}\n\nCan you rewrite the SQL to fix the error?"

            fixed_sql = vn.generate_sql(question=question)

            self.cache.set(id=id, field="sql", value=fixed_sql)

            return jsonify(
                {
                    "type": "sql",
                    "id": id,
                    "text": fixed_sql,
                }
            )


        @self.flask_app.route('/api/v0/update_sql', methods=['POST'])
        @self.requires_auth
        @self.requires_cache([])
        def update_sql(user: any, id: str):
            """
            Update SQL
            ---
            parameters:
              - name: user
                in: query
              - name: id
                in: query|body
                type: string
                required: true
              - name: sql
                in: body
                type: string
                required: true
            responses:
              200:
                schema:
                  type: object
                  properties:
                    type:
                      type: string
                      default: sql
                    id:
                      type: string
                    text:
                      type: string
            """
            sql = flask.request.json.get('sql')

            if sql is None:
                return jsonify({"type": "error", "error": "No sql provided"})

            self.cache.set(id=id, field='sql', value=sql)

            return jsonify(
                {
                    "type": "sql",
                    "id": id,
                    "text": sql,
                })

        @self.flask_app.route("/api/v0/download_csv", methods=["GET"])
        @self.requires_auth
        @self.requires_cache(["df"])
        def download_csv(user: any, id: str, df):
            """
            Download CSV
            ---
            parameters:
              - name: user
                in: query
              - name: id
                in: query|body
                type: string
                required: true
            responses:
              200:
                description: download CSV
            """
            csv = df.to_csv()

            return Response(
                csv,
                mimetype="text/csv",
                headers={"Content-disposition": f"attachment; filename={id}.csv"},
            )
        @self.flask_app.route("/api/v0/get_json", methods=["GET"])
        @self.requires_auth
        @self.requires_cache(["df"])
        def get_json(user: any, id: str, df):
            """
            Get JSON Data
            ---
            parameters:
              - name: user
                in: query
              - name: id
                in: query|body
                type: string
                required: true
            responses:
              200:
                description: Return raw JSON
            """
            json_data = df.to_json(orient='records')  # Convert DataFrame to JSON

            return jsonify({"id": id, "data": json.loads(json_data)})  # Return raw JSON

        @self.flask_app.route("/api/v0/generate_plotly_figure", methods=["GET"])
        @self.requires_auth
        @self.requires_cache(["df", "question", "sql"])
        def generate_plotly_figure(user: any, id: str, df, question, sql):
            """
            Generate plotly figure
            ---
            parameters:
              - name: user
                in: query
              - name: id
                in: query|body
                type: string
                required: true
              - name: chart_instructions
                in: body
                type: string
            responses:
              200:
                schema:
                  type: object
                  properties:
                    type:
                      type: string
                      default: plotly_figure
                    id:
                      type: string
                    fig:
                      type: object
            """
            chart_instructions = flask.request.args.get('chart_instructions')

            try:
                # If chart_instructions is not set then attempt to retrieve the code from the cache
                if chart_instructions is None or len(chart_instructions) == 0:
                    code = self.cache.get(id=id, field="plotly_code")
                else:
                    question = f"{question}. When generating the chart, use these special instructions: {chart_instructions}"
                    code = vn.generate_plotly_code(
                        question=question,
                        sql=sql,
                        df_metadata=f"Running df.dtypes gives:\n {df.dtypes}",
                    )
                    self.cache.set(id=id, field="plotly_code", value=code)

                fig = vn.get_plotly_figure(plotly_code=code, df=df, dark_mode=False)
                fig_json = fig.to_json()

                self.cache.set(id=id, field="fig_json", value=fig_json)

                return jsonify(
                    {
                        "type": "plotly_figure",
                        "id": id,
                        "fig": fig_json,
                    }
                )
            except Exception as e:
                # Print the stack trace
                import traceback

                traceback.print_exc()

                return jsonify({"type": "error", "error": str(e)})

        @self.flask_app.route("/api/v0/get_training_data", methods=["GET"])
        @self.requires_auth
        def get_training_data(user: any):
            """
            Get all training data
            ---
            parameters:
              - name: user
                in: query
            responses:
              200:
                schema:
                  type: object
                  properties:
                    type:
                      type: string
                      default: df
                    id:
                      type: string
                      default: training_data
                    df:
                      type: object
            """
            df = vn.get_training_data()

            if df is None or len(df) == 0:
                return jsonify(
                    {
                        "type": "error",
                        "error": "No training data found. Please add some training data first.",
                    }
                )

            return jsonify(
                {
                    "type": "df",
                    "id": "training_data",
                    "df": df.to_json(orient="records"),
                }
            )

        @self.flask_app.route("/api/v0/remove_training_data", methods=["POST"])
        @self.requires_auth
        def remove_training_data(user: any):
            """
            Remove training data
            ---
            parameters:
              - name: user
                in: query
              - name: id
                in: body
                type: string
                required: true
            responses:
              200:
                schema:
                  type: object
                  properties:
                    success:
                      type: boolean
            """
            # Get id from the JSON body
            id = flask.request.json.get("id")

            if id is None:
                return jsonify({"type": "error", "error": "No id provided"})

            if vn.remove_training_data(id=id):
                return jsonify({"success": True})
            else:
                return jsonify(
                    {"type": "error", "error": "Couldn't remove training data"}
                )

        @self.flask_app.route("/api/v0/train", methods=["POST"])
        @self.requires_auth
        def add_training_data(user: any):
            """
            Add training data
            ---
            parameters:
              - name: user
                in: query
              - name: question
                in: body
                type: string
              - name: sql
                in: body
                type: string
              - name: ddl
                in: body
                type: string
              - name: documentation
                in: body
                type: string
            responses:
              200:
                schema:
                  type: object
                  properties:
                    id:
                      type: string
            """
            question = flask.request.json.get("question")
            sql = flask.request.json.get("sql")
            ddl = flask.request.json.get("ddl")
            documentation = flask.request.json.get("documentation")

            try:
                id = vn.train(
                    question=question, sql=sql, ddl=ddl, documentation=documentation
                )

                return jsonify({"id": id})
            except Exception as e:
                print("TRAINING ERROR", e)
                return jsonify({"type": "error", "error": str(e)})

        @self.flask_app.route("/api/v0/create_function", methods=["GET"])
        @self.requires_auth
        @self.requires_cache(["question", "sql"])
        def create_function(user: any, id: str, question: str, sql: str):
            """
            Create function
            ---
            parameters:
              - name: user
                in: query
              - name: id
                in: query|body
                type: string
                required: true
            responses:
              200:
                schema:
                  type: object
                  properties:
                    type:
                      type: string
                      default: function_template
                    id:
                      type: string
                    function_template:
                      type: object
            """
            plotly_code = self.cache.get(id=id, field="plotly_code")

            if plotly_code is None:
                plotly_code = ""

            function_data = self.vn.create_function(question=question, sql=sql, plotly_code=plotly_code)

            return jsonify(
                {
                    "type": "function_template",
                    "id": id,
                    "function_template": function_data,
                }
            )

        @self.flask_app.route("/api/v0/update_function", methods=["POST"])
        @self.requires_auth
        def update_function(user: any):
            """
            Update function
            ---
            parameters:
              - name: user
                in: query
              - name: old_function_name
                in: body
                type: string
                required: true
              - name: updated_function
                in: body
                type: object
                required: true
            responses:
              200:
                schema:
                  type: object
                  properties:
                    success:
                      type: boolean
            """
            old_function_name = flask.request.json.get("old_function_name")
            updated_function = flask.request.json.get("updated_function")

            print("old_function_name", old_function_name)
            print("updated_function", updated_function)

            updated = vn.update_function(old_function_name=old_function_name, updated_function=updated_function)

            return jsonify({"success": updated})

        @self.flask_app.route("/api/v0/delete_function", methods=["POST"])
        @self.requires_auth
        def delete_function(user: any):
            """
            Delete function
            ---
            parameters:
              - name: user
                in: query
              - name: function_name
                in: body
                type: string
                required: true
            responses:
              200:
                schema:
                  type: object
                  properties:
                    success:
                      type: boolean
            """
            function_name = flask.request.json.get("function_name")

            return jsonify({"success": vn.delete_function(function_name=function_name)})

        @self.flask_app.route("/api/v0/generate_followup_questions", methods=["GET"])
        @self.requires_auth
        @self.requires_cache(["df", "question", "sql"])
        def generate_followup_questions(user: any, id: str, df, question, sql):
            """
            Generate followup questions
            ---
            parameters:
              - name: user
                in: query
              - name: id
                in: query|body
                type: string
                required: true
            responses:
              200:
                schema:
                  type: object
                  properties:
                    type:
                      type: string
                      default: question_list
                    questions:
                      type: array
                      items:
                        type: string
                    header:
                      type: string
            """
            if self.allow_llm_to_see_data:
                followup_questions = vn.generate_followup_questions(
                    question=question, sql=sql, df=df
                )
                if followup_questions is not None and len(followup_questions) > 5:
                    followup_questions = followup_questions[:5]

                self.cache.set(id=id, field="followup_questions", value=followup_questions)

                return jsonify(
                    {
                        "type": "question_list",
                        "id": id,
                        "questions": followup_questions,
                        "header": "Here are some potential followup questions:",
                    }
                )
            else:
                self.cache.set(id=id, field="followup_questions", value=[])
                return jsonify(
                    {
                        "type": "question_list",
                        "id": id,
                        "questions": [],
                        "header": "Followup Questions can be enabled if you set allow_llm_to_see_data=True",
                    }
                )

        @self.flask_app.route("/api/v0/generate_summary", methods=["GET"])
        @self.requires_auth
        @self.requires_cache(["df", "question"])
        def generate_summary(user: any, id: str, df, question):
            """
            Generate summary
            ---
            parameters:
              - name: user
                in: query
              - name: id
                in: query|body
                type: string
                required: true
            responses:
              200:
                schema:
                  type: object
                  properties:
                    type:
                      type: string
                      default: text
                    id:
                      type: string
                    text:
                      type: string
            """
            if self.allow_llm_to_see_data:
                summary = vn.generate_summary(question=question, df=df)

                self.cache.set(id=id, field="summary", value=summary)

                return jsonify(
                    {
                        "type": "text",
                        "id": id,
                        "text": summary,
                    }
                )
            else:
                return jsonify(
                    {
                        "type": "text",
                        "id": id,
                        "text": "Summarization can be enabled if you set allow_llm_to_see_data=True",
                    }
                )

        @self.flask_app.route("/api/v0/load_question", methods=["GET"])
        @self.requires_auth
        def load_question(user: any):
            """
            Load question from the database using an ID.
            ---
            parameters:
              - name: id
                in: query
                type: string
                required: true
            responses:
              200:
                schema:
                  type: object
                  properties:
                    type:
                      type: string
                      default: question_cache
                    id:
                      type: string
                    question:
                      type: string
                    sql:
                      type: string
            """
            # Get 'id' from query parameters
            id = request.args.get('id')
            if not id:
                return jsonify({"type": "error", "error": "ID is required"}), 400

            try:
                # Connect to PostgreSQL
                conn = psycopg2.connect(
                    host='localhost',
                    dbname='flat_table',  # Adjust with your database name
                    user='postgres',
                    password='admin',
                    port='5432'
                )
                print("Connected to PostgreSQL")

                # Query the database for the required data (id, question, sql)
                with conn.cursor() as cursor:
                    cursor.execute("""
                        SELECT id, question, sql
                        FROM question_history
                        WHERE id = %s
                    """, (id,))
                    result = cursor.fetchone()

                # Close the database connection
                conn.close()

                if result is None:
                    return jsonify({"type": "error", "error": "Question not found"}), 404

                # Unpack the result
                question_id, question_text, sql_query = result
                print('Result:', result)

                # Return the response with id, question, and sql
                return jsonify(
                    {
                        "type": "question_cache",
                        "id": question_id,
                        "question": question_text,
                        "sql": sql_query
                    }
                ), 200

            except Exception as e:
                print(f"Error fetching from database: {e}")
                return jsonify({"type": "error", "error": str(e)}), 500
                  
        @self.flask_app.route("/api/v0/get_question_history", methods=["GET"])
        @self.requires_auth
        def get_question_history(user: str):
            """
            Get question history
            ---
            parameters:
              - name: user
                in: query
                required: true
            responses:
              200:
                schema:
                  type: object
                  properties:
                    type:
                      type: string
                      default: question_history
                    user:
                      type: object
                      properties:
                        username:
                          type: string
                    questions:
                      type: array
                      items:
                        type: object
                        properties:
                          id:
                            type: string
                          question:
                            type: string
                          sql:
                            type: string
                          timestamp:
                            type: string
            """
            print(f"Fetching question history for user: {user}")  # Debug statement

            # Database connection
            try:
                conn = psycopg2.connect(
                    host='localhost',
                    dbname='flat_table',
                    user='postgres',
                    password='admin',
                    port='5432'
                )
                print("Connected to PostgreSQL")  # Debug statement
            except Exception as e:
                print(f"Error connecting to database: {e}")
                return jsonify({"type": "error", "error": "Database connection error"}), 500

            try:
                with conn.cursor() as cursor:
                    cursor.execute(
                        """
                        SELECT id, question, sql, timestamp 
                        FROM question_history
                        WHERE username = %s
                        ORDER BY timestamp DESC
                        """,
                        (user,)
                    )
                    question_records = cursor.fetchall()
                    
                    # Include 'id', 'question', 'sql', and 'timestamp' in the result
                    questions = [
                        {
                            "id": row[0],
                            "question": row[1],
                            "sql": row[2],
                            "timestamp": row[3].isoformat()  # Format timestamp to ISO
                        }
                        for row in question_records
                    ]
                    print(f"Fetched question history from database for user: {user}")  # Debug statement

            except Exception as e:
                print(f"Error fetching from database: {e}")
                return jsonify({"type": "error", "error": "Database query error"}), 500
            finally:
                conn.close()
                print("Database connection closed")  # Debug statement

            # Return the fetched questions as JSON
            return jsonify(
                {
                    "type": "question_history",
                    "user": {"username": user},
                    "questions": questions,
                }
            ), 200

        @self.flask_app.route("/api/v0/clear_question_history", methods=["DELETE"])
        @self.requires_auth
        def clear_question_history(user: str):
            """
            Clear all question history for a user (Hard Delete).
            ---
            parameters:
              - name: user
                in: query
                required: true
            responses:
              200:
                schema:
                  type: object
                  properties:
                    type:
                      type: string
                      default: clear_history
                    user:
                      type: object
                      properties:
                        username:
                          type: string
                    message:
                      type: string
              500:
                schema:
                  type: object
                  properties:
                    type:
                      type: string
                      default: error
                    error:
                      type: string
            """
            print(f"Attempting to clear question history for user: {user}")  # Log input username

            # Database connection
            try:
                conn = psycopg2.connect(
                    host='localhost',
                    dbname='flat_table',
                    user='postgres',
                    password='admin',
                    port='5432'
                )
                print("Connected to PostgreSQL successfully")  # Log successful DB connection
            except Exception as e:
                print(f"Error connecting to database: {e}")
                return jsonify({"type": "error", "error": "Database connection error"}), 500

            try:
                with conn.cursor() as cursor:
                    # Log before running DELETE query
                    print(f"Executing DELETE query to clear history for user: {user}")

                    cursor.execute(
                        """
                        DELETE FROM question_history
                        WHERE username = %s
                        """,
                        (user,)
                    )

                    # Log number of rows deleted
                    deleted_rows = cursor.rowcount
                    print(f"Rows deleted for user {user}: {deleted_rows}")

                    conn.commit()  # Commit the changes
                    if deleted_rows == 0:
                        print(f"No rows were deleted for user {user}. Please verify if data exists.")  # Log if no rows were deleted

            except Exception as e:
                print(f"Error clearing history from database: {e}")
                return jsonify({"type": "error", "error": "Database query error"}), 500
            finally:
                conn.close()
                print("Database connection closed")  # Log database connection closure

            # Return a success response
            if deleted_rows > 0:
                return jsonify(
                    {
                        "type": "clear_history",
                        "user": {"username": user},
                        "message": "Question history cleared successfully",
                    }
                ), 200
            else:
                return jsonify(
                    {
                        "type": "clear_history",
                        "user": {"username": user},
                        "message": "No history found for the user, nothing was deleted.",
                    }
                ), 200

        @self.flask_app.route("/api/v0/<path:catch_all>", methods=["GET", "POST"])
        def catch_all(catch_all):
            return jsonify(
                {"type": "error", "error": "The rest of the API is not ported yet."}
            )

        if self.debug:
            @self.sock.route("/api/v0/log")
            def sock_log(ws):
                self.ws_clients.append(ws)

                try:
                    while True:
                        message = ws.receive()  # This example just reads and ignores to keep the socket open
                finally:
                    self.ws_clients.remove(ws)

    def run(self, *args, **kwargs):
        """
        Run the Flask app.

        Args:
            *args: Arguments to pass to Flask's run method.
            **kwargs: Keyword arguments to pass to Flask's run method.

        Returns:
            None
        """
        if args or kwargs:
            self.flask_app.run(*args, **kwargs)

        else:
            try:
                from google.colab import output

                output.serve_kernel_port_as_window(8084)
                from google.colab.output import eval_js

                print("Your app is running at:")
                print(eval_js("google.colab.kernel.proxyPort(8084)"))
            except:
                print("Your app is running at:")
                print("http://localhost:8084")

            self.flask_app.run(host="0.0.0.0", port=8084, debug=self.debug, use_reloader=False)


class VannaFlaskApp(VannaFlaskAPI):
    def __init__(
        self,
        vn: VannaBase,
        cache: Cache = MemoryCache(),
        auth: AuthInterface = BasicAuth(),
        debug=True,
        allow_llm_to_see_data=True,
        logo="https://b3336080.smushcdn.com/3336080/wp-content/uploads/2023/10/logo.png",
        title="Welcome to NMSDC AI",
        subtitle="Your AI-powered leads with SQL queries.",
        show_training_data=True,
        suggested_questions=True,
        sql=True,
        table=True,
        csv_download=True,
        chart=False,
        redraw_chart=False,
        auto_fix_sql=True,
        ask_results_correct=True,
        followup_questions=True,
        summarization=True,
        function_generation=False,
        index_html_path=None,
        assets_folder=None,
    ):
        """
        Expose a Flask app that can be used to interact with a Vanna instance.

        Args:
            vn: The Vanna instance to interact with.
            cache: The cache to use. Defaults to MemoryCache, which uses an in-memory cache. You can also pass in a custom cache that implements the Cache interface.
            auth: The authentication method to use. Defaults to NoAuth, which doesn't require authentication. You can also pass in a custom authentication method that implements the AuthInterface interface.
            debug: Show the debug console. Defaults to True.
            allow_llm_to_see_data: Whether to allow the LLM to see data. Defaults to False.
            logo: The logo to display in the UI. Defaults to the Vanna logo.
            title: The title to display in the UI. Defaults to "Welcome to Vanna.AI".
            subtitle: The subtitle to display in the UI. Defaults to "Your AI-powered copilot for SQL queries.".
            show_training_data: Whether to show the training data in the UI. Defaults to True.
            suggested_questions: Whether to show suggested questions in the UI. Defaults to True.
            sql: Whether to show the SQL input in the UI. Defaults to True.
            table: Whether to show the table output in the UI. Defaults to True.
            csv_download: Whether to allow downloading the table output as a CSV file. Defaults to True.
            chart: Whether to show the chart output in the UI. Defaults to True.
            redraw_chart: Whether to allow redrawing the chart. Defaults to True.
            auto_fix_sql: Whether to allow auto-fixing SQL errors. Defaults to True.
            ask_results_correct: Whether to ask the user if the results are correct. Defaults to True.
            followup_questions: Whether to show followup questions. Defaults to True.
            summarization: Whether to show summarization. Defaults to True.
            index_html_path: Path to the index.html. Defaults to None, which will use the default index.html
            assets_folder: The location where you'd like to serve the static assets from. Defaults to None, which will use hardcoded Python variables.

        Returns:
            None
        """
        super().__init__(vn, cache, auth, debug, allow_llm_to_see_data, chart)

        # Configuration settings
        self.config.update({
            "logo": logo,
            "title": title,
            "subtitle": subtitle,
            "show_training_data": show_training_data,
            "suggested_questions": suggested_questions,
            "sql": sql,
            "table": table,
            "csv_download": csv_download,
            "chart": chart,
            "redraw_chart": redraw_chart,
            "auto_fix_sql": auto_fix_sql,
            "ask_results_correct": ask_results_correct,
            "followup_questions": followup_questions,
            "summarization": summarization,
            "function_generation": function_generation and hasattr(vn, "get_function"),
            "version": importlib.metadata.version('vanna')
        })

        self.index_html_path = index_html_path
        self.assets_folder = assets_folder
        self.jinja_env = Environment(loader=FileSystemLoader('/home/ubuntu/miniconda3/lib/python3.12/site-packages/vanna/flask/frontend'))

        @self.flask_app.route("/auth/login", methods=["POST"])
        def login():
            return self.auth.login_handler(flask.request)

        @self.flask_app.route("/auth/callback", methods=["GET"])
        def callback():
            return self.auth.callback_handler(flask.request)

        @self.flask_app.route("/auth/logout", methods=["GET"])
        def logout():
            return self.auth.logout_handler(flask.request)
        
        @self.flask_app.route('/auth/check-session', methods=['GET'])
        def check_session():
            if session.get('username'):  # or whatever key you're using to store user info
                return jsonify({"logged_in": True, "username": session['username']})
            return jsonify({"logged_in": False})

        @self.flask_app.route("/assets/<path:filename>")
        def proxy_assets(filename):
            if self.assets_folder:
                return send_from_directory(self.assets_folder, filename)

            if ".css" in filename:
                return Response(css_content, mimetype="text/css")

            if ".js" in filename:
                return Response(js_content, mimetype="text/javascript")

            # Return 404
            return "File not found", 404


        # Proxy the /vanna.svg file to the remote server
        @self.flask_app.route("/vanna.svg")
        def proxy_vanna_svg():
            remote_url = "https://vanna.ai/img/vanna.svg"
            response = requests.get(remote_url, stream=True)

            # Check if the request to the remote URL was successful
            if response.status_code == 200:
                excluded_headers = [
                    "content-encoding",
                    "content-length",
                    "transfer-encoding",
                    "connection",
                ]
                headers = [
                    (name, value)
                    for (name, value) in response.raw.headers.items()
                    if name.lower() not in excluded_headers
                ]
                return Response(response.content, response.status_code, headers)
            else:
                return "Error fetching file from remote server", response.status_code
        
        @self.flask_app.route("/", defaults={"path": ""})
        @self.flask_app.route("/<path:path>")
        def hello(path: str):
            if self.index_html_path:
                directory = os.path.dirname(self.index_html_path)
                filename = os.path.basename(self.index_html_path)
                return send_from_directory(directory=directory, path=filename)
            return html_content

        @self.flask_app.route("/view_all")
        def view_all():
            """Serve a new page that displays the ID passed in the query parameters."""
            id = request.args.get('id', 'No ID provided')  # Get the 'id' from query parameter
            template = self.jinja_env.get_template('viewAll.html')  # Load the template explicitly
            return template.render(id=id)  # Render the template with the 
        def run(self):
            self.flask_app.run(debug=True)

                    # Define the route to serve index.html
        @self.flask_app.route("/new")
        def serve_index():
            """Serve the index.html page."""
            template = self.jinja_env.get_template('index.html')  # Load the index.html template
            return template.render()  # Render the index.html templat
