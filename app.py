from vanna.flask import VannaFlaskApp
from vanna.chromadb import ChromaDB_VectorStore
from vanna.mistral import Mistral
import psycopg2
from vanna.flask.auth import AuthInterface
import flask
from flask_cors import CORS


class MyVanna(ChromaDB_VectorStore, Mistral):
    def __init__(self, config=None):
        ChromaDB_VectorStore.__init__(self, config=config)
        Mistral.__init__(self, config={'api_key': 'mistral_api_key', 'model': 'mistral-small-latest'})

# Instantiate MyVanna and connect to PostgreSQL
vn = MyVanna()
vn.connect_to_postgres(
    host='localhost', 
    dbname='flat_table', 
    user='postgres', 
    password='admin', 
    port='5432'
)


class SimplePassword(AuthInterface):
    def __init__(self, users: dict):
        self.users = users

    def get_user(self, flask_request) -> any:
        return flask_request.cookies.get('user')

    def is_logged_in(self, user: any) -> bool:
        return user is not None

    def override_config_for_user(self, user: any, config: dict) -> dict:
        return config

    def login_form(self) -> str:
        return '''
  <div class="p-4 sm:p-7">
    <div class="text-center">
      <h1 class="block text-2xl font-bold text-gray-800 dark:text-white">Sign in</h1>
      <p class="mt-2 text-sm text-gray-600 dark:text-gray-400">

      </p>
    </div>

    <div class="mt-5">

      <!-- Form -->
      <form action="/auth/login" method="POST">
        <div class="grid gap-y-4">
          <!-- Form Group -->
          <div>
            <label for="email" class="block text-sm mb-2 dark:text-white">Email address</label>
            <div class="relative">
              <input type="email" id="email" type="email" name="email" class="py-3 px-4 block w-full border border-gray-200 rounded-lg text-sm focus:border-blue-500 focus:ring-blue-500 disabled:opacity-50 disabled:pointer-events-none dark:bg-slate-900 dark:border-gray-700 dark:text-gray-400 dark:focus:ring-gray-600" required aria-describedby="email-error">
              <div class="hidden absolute inset-y-0 end-0 pointer-events-none pe-3">
                <svg class="size-5 text-red-500" width="16" height="16" fill="currentColor" viewBox="0 0 16 16" aria-hidden="true">
                  <path d="M16 8A8 8 0 1 1 0 8a8 8 0 0 1 16 0zM8 4a.905.905 0 0 0-.9.995l.35 3.507a.552.552 0 0 0 1.1 0l.35-3.507A.905.905 0 0 0 8 4zm.002 6a1 1 0 1 0 0 2 1 1 0 0 0 0-2z"/>
                </svg>
              </div>
            </div>
            <p class="hidden text-xs text-red-600 mt-2" id="email-error">Please include a valid email address so we can get back to you</p>
          </div>
          <!-- End Form Group -->

          <!-- Form Group -->
          <div>
            <div class="flex justify-between items-center">
              <label for="password" class="block text-sm mb-2 dark:text-white">Password</label>

            </div>
            <div class="relative">
              <input type="password" id="password" name="password" class="py-3 px-4 block w-full border border-gray-200 rounded-lg text-sm focus:border-blue-500 focus:ring-blue-500 disabled:opacity-50 disabled:pointer-events-none dark:bg-slate-900 dark:border-gray-700 dark:text-gray-400 dark:focus:ring-gray-600" required aria-describedby="password-error">
              <div class="hidden absolute inset-y-0 end-0 pointer-events-none pe-3">
                <svg class="size-5 text-red-500" width="16" height="16" fill="currentColor" viewBox="0 0 16 16" aria-hidden="true">
                  <path d="M16 8A8 8 0 1 1 0 8a8 8 0 0 1 16 0zM8 4a.905.905 0 0 0-.9.995l.35 3.507a.552.552 0 0 0 1.1 0l.35-3.507A.905.905 0 0 0 8 4zm.002 6a1 1 0 1 0 0 2 1 1 0 0 0 0-2z"/>
                </svg>
              </div>
            </div>
            <p class="hidden text-xs text-red-600 mt-2" id="password-error">8+ characters required</p>
          </div>
          <!-- End Form Group -->

          <button type="submit" class="w-full py-3 px-4 inline-flex justify-center items-center gap-x-2 text-sm font-semibold rounded-lg border border-transparent bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-50 disabled:pointer-events-none">Sign in</button>
        </div>
      </form>
      <!-- End Form -->
    </div>
  </div>
        '''
    def login_handler(self, flask_request) -> str:
        if flask_request.is_json:
            data = flask_request.get_json()
        else:
            data = flask_request.form

        email = data.get('email')
        password = data.get('password')

        for user in self.users:
            if user["email"] == email and user["password"] == password:
                response = flask.make_response('Logged in as ' + email)
                
                # Set cookie with secure=False for local testing
                response.set_cookie(
                    'user', 
                    email, 
                    samesite='Lax',  # or 'None' if needed for cross-site
                    secure=False,    # Set True for HTTPS in production
                    path='/'
                )
                
                print(f'Logged in as {email}')  
                
                # Redirect to the front-end application
                response.headers['Location'] = 'http://localhost:5173/'
                response.status_code = 302
                return response

        return 'Login failed', 401  # Unauthorized response



    def callback_handler(self, flask_request) -> str:
        user = flask_request.args['user']
        response = flask.make_response('Logged in as ' + user)
        response.set_cookie('user', user)
        return response

    def logout_handler(self, flask_request) -> str:
        response = flask.make_response('Logged out')
        response.delete_cookie('user')
        return response

# Instantiate VannaFlaskApp with authentication
app = VannaFlaskApp(
    vn=vn,
    auth=SimplePassword(users=[
        {"email": "rohitdoc15@gmail.com", "password": "password"},
        {"email": "user1@example.com", "password": "user1pass"},
        {"email": "user2@example.com", "password": "user2pass"},
        {"email": "manager@example.com", "password": "manager123"},
        {"email": "guest@example.com", "password": "guestpass"}
    ]),
    allow_llm_to_see_data=True,
    title="Hello World",
    subtitle="This is a test",
    show_training_data=True,
    sql=True,
    table=True,
    chart=True,
    summarization=False,
    ask_results_correct=True,
)
CORS(
    app.flask_app,  # Assuming app.flask_app is the underlying Flask instance
    supports_credentials=True,
    resources={r"/*": {"origins": "http://localhost:5173"}}
)


# Run the app
app.run()
